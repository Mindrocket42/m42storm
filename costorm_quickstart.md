# Co-STORM Quickstart Guide for Novices

This guide provides simplified steps to get a basic Co-STORM example running, focusing on the practical steps without diving into the advanced Python mechanics used internally.

## 1. Prerequisites

*   **Python:** Ensure you have Python installed (version 3.11 is recommended). You can download it from [python.org](https://www.python.org/).
*   **Conda (Recommended):** A package and environment manager like Conda makes managing dependencies easier. You can install it via [Anaconda](https://www.anaconda.com/download) or [Miniconda](https://docs.conda.io/projects/miniconda/en/latest/).
*   **Git:** You'll need Git to clone the repository. Download it from [git-scm.com](https://git-scm.com/downloads).
*   **OpenAI API Key:** Co-STORM uses OpenAI's models for its core functions, including the default search capability. You need an API key from [OpenAI](https://platform.openai.com/api-keys).

## 2. Installation

1.  **Open your terminal or command prompt.**
2.  **Clone the repository:**
    ```bash
    git clone https://github.com/stanford-oval/storm.git
    cd storm
    ```
3.  **Create and activate a Conda environment (Recommended):**
    ```bash
    conda create -n storm python=3.11
    conda activate storm
    ```
    *(If not using Conda, you might use `python -m venv storm_env` and `source storm_env/bin/activate` or `storm_env\Scripts\activate`)*
4.  **Install required packages:**
    ```bash
    pip install -r requirements.txt
    ```

## 3. API Key Setup

Co-STORM needs API keys to work. The easiest way is using a `secrets.toml` file.

1.  **Create a file named `secrets.toml` in the main `storm` directory** (the one you `cd`-ed into).
2.  **Add your OpenAI API key to the file:**

    ```toml
    # secrets.toml

    # ============ language model configurations ============
    # Set up OpenAI API key. Required for default models and search.
    OPENAI_API_KEY="your_openai_api_key_here"

    # If you are using the API service provided by OpenAI:
    OPENAI_API_TYPE="openai"

    # # If you are using the API service provided by Microsoft Azure:
    # OPENAI_API_TYPE="azure"
    # AZURE_API_BASE="your_azure_api_base_url"
    # AZURE_API_VERSION="your_azure_api_version"

    # ============ retriever configurations ============
    # The default retriever GPT4oMiniSearchRM uses OPENAI_API_KEY (set above).
    # Add keys here if you plan to use AzureAI Search or VectorRM later.

    # ============ encoder configurations ============
    # The default encoder uses the OpenAI API key as well.
    ENCODER_API_TYPE="openai"
    ```

3.  **Replace `"your_openai_api_key_here"` with your actual OpenAI API key.**
4.  Save the file.

## 4. Running a Basic Co-STORM Example

Let's run the example that uses GPT models.

1.  **Make sure you are in the `storm` directory in your terminal and your `storm` environment is active.**
2.  **Run the example script:**

    ```bash
    python examples/costorm_examples/run_costorm_gpt.py --output-dir ./results/co-storm-quickstart
    ```
    *   `python examples/costorm_examples/run_costorm_gpt.py`: This tells Python to run the specific example script.
    *   `--output-dir ./results/co-storm-quickstart`: This tells the script where to save the output files (it will create the directory if it doesn't exist).

3.  **Enter a topic:** The script will prompt you to enter a topic. Type something like "Artificial Intelligence" or "Climate Change" and press Enter.

4.  **Wait:** Co-STORM will now start working. It involves multiple steps (researching, discussing, generating content) using the language models via your API key. This can take some time and will use OpenAI credits. You'll see output in your terminal showing the progress.

5.  **Find the results:** Once finished, look inside the `./results/co-storm-quickstart` directory (or whatever you named your output directory). You'll find files containing the conversation logs, generated knowledge base, and potentially a final report or mind map, depending on the specific example's configuration.

## Next Steps

This quickstart runs a default configuration. You can explore other scripts in the `examples/costorm_examples` directory and modify parameters (like the topic or output directory) as needed. Refer back to the main `README.md` for more advanced configurations and details about customizing different parts of the system. 