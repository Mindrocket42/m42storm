import logging
import os
from typing import Callable, Union, List
import json

import backoff
import dspy
import requests
from dsp import backoff_hdlr, giveup_hdlr

from .utils import WebPageHelper


class GPT4oMiniSearchRM(dspy.Retrieve):
    """Retrieves search results using the gpt-4o-mini-search-preview model via dspy.OpenAI."""

    def __init__(self, openai_api_key: str = None, k: int = 3, model: str = "gpt-4o-mini-search-preview", **kwargs):
        super().__init__(k=k)
        if not openai_api_key:
            openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OpenAI API key must be provided via openai_api_key parameter or OPENAI_API_KEY environment variable.")
        
        self.llm = dspy.OpenAI(model=model, api_key=openai_api_key, **kwargs)
        self.usage = 0
        # TODO: Define a dspy.Signature for the search task if needed, or use direct call.

    def get_usage_and_reset(self):
        # Note: dspy.OpenAI might track token usage internally. 
        # This method might need adjustment based on how usage is tracked/reported.
        usage = self.usage
        self.usage = 0
        return {"GPT4oMiniSearchRM_Queries": usage}

    @backoff.on_exception(backoff.expo, Exception, max_tries=3, on_backoff=backoff_hdlr, on_giveup=giveup_hdlr)
    def _call_llm(self, query: str):
        # Placeholder: Direct call to the LLM. This might need a proper Signature.
        # Assuming the LLM returns a JSON string with search results.
        # Example prompt (adjust as needed):
        prompt = f"Perform a web search for: {query}\\nReturn the top {self.k} results as a JSON list, where each item has 'url', 'title', and 'snippet' keys."
        response = self.llm(prompt)
        # Assuming the first choice's message content holds the result
        # This structure depends heavily on dspy.OpenAI's return format
        if isinstance(response, list) and len(response) > 0:
             # If response is already parsed list by dspy based on signature
             # This part needs verification based on actual dspy behavior
             raw_results = response[0] 
        elif hasattr(response, 'choices') and len(response.choices) > 0:
             # Standard OpenAI API response structure
             raw_results = response.choices[0].message.content
        elif isinstance(response, str): 
             # Simple string response
             raw_results = response
        else:
             # Fallback or error handling
             logging.error(f"Unexpected LLM response format for query '{query}': {type(response)}")
             raw_results = "[]" # Default to empty list string

        logging.debug(f"Raw LLM Search Results for '{query}': {raw_results}")
        return raw_results

    def forward(self, query_or_queries: Union[str, List[str]], exclude_urls: List[str] = None):
        """Search using gpt-4o-mini-search-preview.

        Args:
            query_or_queries (Union[str, List[str]]): The query or queries to search for.
            exclude_urls (List[str]): Optional list of URLs to exclude (best effort).

        Returns:
            a list of Dicts, each dict has keys 'url', 'title', 'description'/'snippet'.
        """
        queries = (
            [query_or_queries]
            if isinstance(query_or_queries, str)
            else query_or_queries
        )
        self.usage += len(queries)
        collected_results = []

        for query in queries:
            try:
                raw_response_str = self._call_llm(query)
                
                # Attempt to parse the JSON response from the LLM
                try:
                    parsed_results = json.loads(raw_response_str)
                    if not isinstance(parsed_results, list):
                        logging.warning(f"LLM response for '{query}' was not a JSON list: {raw_response_str}")
                        parsed_results = []
                except json.JSONDecodeError:
                    logging.error(f"Failed to decode JSON response for query '{query}': {raw_response_str}")
                    parsed_results = [] # Default to empty list on parse failure

                # Format results into the expected structure
                for result in parsed_results:
                    if isinstance(result, dict) and 'url' in result and 'title' in result and 'snippet' in result:
                        # Basic filtering based on exclude_urls if provided
                        if exclude_urls and result['url'] in exclude_urls:
                            continue
                        
                        # Map snippet to description for compatibility if needed, or use snippet directly
                        formatted_result = {
                            'url': result.get('url'),
                            'title': result.get('title'),
                            'description': result.get('snippet'), # Or result.get('description') if LLM provides that
                            'snippets': [result.get('snippet')] # Often the main snippet is used here
                        }
                        collected_results.append(formatted_result)
                    else:
                        logging.warning(f"Skipping malformed result item for query '{query}': {result}")

            except Exception as e:
                logging.error(f"Error processing query '{query}' with GPT4oMiniSearchRM: {e}")
                # Optionally add a dummy error result or just skip

        # Ensure we don't exceed self.k results overall if multiple queries were processed
        # Although the prompt asks for k results per query, aggregation might exceed k.
        # Depending on desired behavior, might need truncation here.
        # return collected_results[:self.k] # Option 1: Truncate overall
        return collected_results # Option 2: Return all collected results


class VectorRM(dspy.Retrieve):
    """Retrieve information from custom documents using Qdrant.

    To be compatible with STORM, the custom documents should have the following fields:
        - content: The main text content of the document.
        - title: The title of the document.
        - url: The URL of the document. STORM use url as the unique identifier of the document, so ensure different
            documents have different urls.
        - description (optional): The description of the document.
    The documents should be stored in a CSV file.
    """

    def __init__(
        self,
        collection_name: str,
        embedding_model: str,
        device: str = "mps",
        k: int = 3,
    ):
        from langchain_huggingface import HuggingFaceEmbeddings

        """
        Params:
            collection_name: Name of the Qdrant collection.
            embedding_model: Name of the Hugging Face embedding model.
            device: Device to run the embeddings model on, can be "mps", "cuda", "cpu".
            k: Number of top chunks to retrieve.
        """
        super().__init__(k=k)
        self.usage = 0
        # check if the collection is provided
        if not collection_name:
            raise ValueError("Please provide a collection name.")
        # check if the embedding model is provided
        if not embedding_model:
            raise ValueError("Please provide an embedding model.")

        model_kwargs = {"device": device}
        encode_kwargs = {"normalize_embeddings": True}
        self.model = HuggingFaceEmbeddings(
            model_name=embedding_model,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
        )

        self.collection_name = collection_name
        self.client = None
        self.qdrant = None

    def _check_collection(self):
        from langchain_qdrant import Qdrant

        """
        Check if the Qdrant collection exists and create it if it does not.
        """
        if self.client is None:
            raise ValueError("Qdrant client is not initialized.")
        if self.client.collection_exists(collection_name=f"{self.collection_name}"):
            print(
                f"Collection {self.collection_name} exists. Loading the collection..."
            )
            self.qdrant = Qdrant(
                client=self.client,
                collection_name=self.collection_name,
                embeddings=self.model,
            )
        else:
            raise ValueError(
                f"Collection {self.collection_name} does not exist. Please create the collection first."
            )

    def init_online_vector_db(self, url: str, api_key: str):
        from qdrant_client import QdrantClient

        """
        Initialize the Qdrant client that is connected to an online vector store with the given URL and API key.

        Args:
            url (str): URL of the Qdrant server.
            api_key (str): API key for the Qdrant server.
        """
        if api_key is None:
            if not os.getenv("QDRANT_API_KEY"):
                raise ValueError("Please provide an api key.")
            api_key = os.getenv("QDRANT_API_KEY")
        if url is None:
            raise ValueError("Please provide a url for the Qdrant server.")

        try:
            self.client = QdrantClient(url=url, api_key=api_key)
            self._check_collection()
        except Exception as e:
            raise ValueError(f"Error occurs when connecting to the server: {e}")

    def init_offline_vector_db(self, vector_store_path: str):
        from qdrant_client import QdrantClient

        """
        Initialize the Qdrant client that is connected to an offline vector store with the given vector store folder path.

        Args:
            vector_store_path (str): Path to the vector store.
        """
        if vector_store_path is None:
            raise ValueError("Please provide a folder path.")

        try:
            self.client = QdrantClient(path=vector_store_path)
            self._check_collection()
        except Exception as e:
            raise ValueError(f"Error occurs when loading the vector store: {e}")

    def get_usage_and_reset(self):
        usage = self.usage
        self.usage = 0

        return {"VectorRM": usage}

    def get_vector_count(self):
        """
        Get the count of vectors in the collection.

        Returns:
            int: Number of vectors in the collection.
        """
        return self.qdrant.client.count(collection_name=self.collection_name)

    def forward(self, query_or_queries: Union[str, List[str]], exclude_urls: List[str]):
        """
        Search in your data for self.k top passages for query or queries.

        Args:
            query_or_queries (Union[str, List[str]]): The query or queries to search for.
            exclude_urls (List[str]): Dummy parameter to match the interface. Does not have any effect.

        Returns:
            a list of Dicts, each dict has keys of 'description', 'snippets' (list of strings), 'title', 'url'
        """
        queries = (
            [query_or_queries]
            if isinstance(query_or_queries, str)
            else query_or_queries
        )
        self.usage += len(queries)
        collected_results = []
        for query in queries:
            related_docs = self.qdrant.similarity_search_with_score(query, k=self.k)
            for i in range(len(related_docs)):
                doc = related_docs[i][0]
                collected_results.append(
                    {
                        "description": doc.metadata["description"],
                        "snippets": [doc.page_content],
                        "title": doc.metadata["title"],
                        "url": doc.metadata["url"],
                    }
                )

        return collected_results


class StanfordOvalArxivRM(dspy.Retrieve):
    """[Alpha] This retrieval class is for internal use only, not intended for the public."""

    def __init__(self, endpoint, k=3, rerank=True):
        super().__init__(k=k)
        self.endpoint = endpoint
        self.usage = 0
        self.rerank = rerank

    def get_usage_and_reset(self):
        usage = self.usage
        self.usage = 0

        return {"StanfordOvalArxivRM": usage}

    def _retrieve(self, query: str):
        payload = {"query": query, "num_blocks": self.k, "rerank": self.rerank}

        response = requests.post(
            self.endpoint, json=payload, headers={"Content-Type": "application/json"}
        )

        # Check if the request was successful
        if response.status_code == 200:
            response_data_list = response.json()[0]["results"]
            results = []
            for response_data in response_data_list:
                result = {
                    "title": response_data["document_title"],
                    "url": response_data["url"],
                    "snippets": [response_data["content"]],
                    "description": response_data.get("description", "N/A"),
                    "meta": {
                        key: value
                        for key, value in response_data.items()
                        if key not in ["document_title", "url", "content"]
                    },
                }

                results.append(result)

            return results
        else:
            raise Exception(
                f"Error: Unable to retrieve results. Status code: {response.status_code}"
            )

    def forward(
        self, query_or_queries: Union[str, List[str]], exclude_urls: List[str] = []
    ):
        collected_results = []
        queries = (
            [query_or_queries]
            if isinstance(query_or_queries, str)
            else query_or_queries
        )

        for query in queries:
            try:
                results = self._retrieve(query)
                collected_results.extend(results)
            except Exception as e:
                logging.error(f"Error occurs when searching query {query}: {e}")
        return collected_results


class AzureAISearch(dspy.Retrieve):
    """Retrieve information from custom queries using Azure AI Search.

    General Documentation: https://learn.microsoft.com/en-us/azure/search/search-create-service-portal.
    Python Documentation: https://learn.microsoft.com/en-us/python/api/overview/azure/search-documents-readme?view=azure-python.
    """

    def __init__(
        self,
        azure_ai_search_api_key=None,
        azure_ai_search_url=None,
        azure_ai_search_index_name=None,
        k=3,
        is_valid_source: Callable = None,
    ):
        """
        Params:
            azure_ai_search_api_key: Azure AI Search API key. Check out https://learn.microsoft.com/en-us/azure/search/search-security-api-keys?tabs=rest-use%2Cportal-find%2Cportal-query
                "API key" section
            azure_ai_search_url: Custom Azure AI Search Endpoint URL. Check out https://learn.microsoft.com/en-us/azure/search/search-create-service-portal#name-the-service
            azure_ai_search_index_name: Custom Azure AI Search Index Name. Check out https://learn.microsoft.com/en-us/azure/search/search-how-to-create-search-index?tabs=portal
            k: Number of top results to retrieve.
            is_valid_source: Optional function to filter valid sources.
            min_char_count: Minimum character count for the article to be considered valid.
            snippet_chunk_size: Maximum character count for each snippet.
            webpage_helper_max_threads: Maximum number of threads to use for webpage helper.
        """
        super().__init__(k=k)

        try:
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents import SearchClient
        except ImportError as err:
            raise ImportError(
                "AzureAISearch requires `pip install azure-search-documents`."
            ) from err

        if not azure_ai_search_api_key and not os.environ.get(
            "AZURE_AI_SEARCH_API_KEY"
        ):
            raise RuntimeError(
                "You must supply azure_ai_search_api_key or set environment variable AZURE_AI_SEARCH_API_KEY"
            )
        elif azure_ai_search_api_key:
            self.azure_ai_search_api_key = azure_ai_search_api_key
        else:
            self.azure_ai_search_api_key = os.environ["AZURE_AI_SEARCH_API_KEY"]

        if not azure_ai_search_url and not os.environ.get("AZURE_AI_SEARCH_URL"):
            raise RuntimeError(
                "You must supply azure_ai_search_url or set environment variable AZURE_AI_SEARCH_URL"
            )
        elif azure_ai_search_url:
            self.azure_ai_search_url = azure_ai_search_url
        else:
            self.azure_ai_search_url = os.environ["AZURE_AI_SEARCH_URL"]

        if not azure_ai_search_index_name and not os.environ.get(
            "AZURE_AI_SEARCH_INDEX_NAME"
        ):
            raise RuntimeError(
                "You must supply azure_ai_search_index_name or set environment variable AZURE_AI_SEARCH_INDEX_NAME"
            )
        elif azure_ai_search_index_name:
            self.azure_ai_search_index_name = azure_ai_search_index_name
        else:
            self.azure_ai_search_index_name = os.environ["AZURE_AI_SEARCH_INDEX_NAME"]

        self.usage = 0

        # If not None, is_valid_source shall be a function that takes a URL and returns a boolean.
        if is_valid_source:
            self.is_valid_source = is_valid_source
        else:
            self.is_valid_source = lambda x: True

    def get_usage_and_reset(self):
        usage = self.usage
        self.usage = 0

        return {"AzureAISearch": usage}

    def forward(
        self, query_or_queries: Union[str, List[str]], exclude_urls: List[str] = []
    ):
        """Search with Azure Open AI for self.k top passages for query or queries

        Args:
            query_or_queries (Union[str, List[str]]): The query or queries to search for.
            exclude_urls (List[str]): A list of urls to exclude from the search results.

        Returns:
            a list of Dicts, each dict has keys of 'description', 'snippets' (list of strings), 'title', 'url'
        """
        try:
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents import SearchClient
        except ImportError as err:
            raise ImportError(
                "AzureAISearch requires `pip install azure-search-documents`."
            ) from err
        queries = (
            [query_or_queries]
            if isinstance(query_or_queries, str)
            else query_or_queries
        )
        self.usage += len(queries)
        collected_results = []

        client = SearchClient(
            self.azure_ai_search_url,
            self.azure_ai_search_index_name,
            AzureKeyCredential(self.azure_ai_search_api_key),
        )
        for query in queries:
            try:
                # https://learn.microsoft.com/en-us/python/api/azure-search-documents/azure.search.documents.searchclient?view=azure-python#azure-search-documents-searchclient-search
                results = client.search(search_text=query, top=self.k) # Corrected top parameter

                for result in results:
                    document = {
                        "url": result["metadata_storage_path"],
                        "title": result["title"],
                        "description": "N/A",
                        "snippets": [result["chunk"]],
                    }
                    collected_results.append(document)
            except Exception as e:
                logging.error(f"Error occurs when searching query {query}: {e}")

        return collected_results
