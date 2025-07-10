# Gemini Insights for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

**Gemini Insights** is a custom component for Home Assistant that leverages the power of Google's Gemini Pro API to analyze data from your Home Assistant entities. It can provide you with:

1.  **General Insights:** Useful observed trends from your smart home data.
2.  **Alerts:** Notifications if anything looks out of the ordinary.
3.  **Summaries:** Daily, weekly, or monthly (depending on your prompt) summaries of specific entities.

This component periodically fetches data from selected entities, sends it to the Gemini API with a customizable prompt, and then displays the generated insights, alerts, and summaries as sensor states within Home Assistant.

## Prerequisites

*   **Home Assistant:** A running instance of Home Assistant.
*   **Google Gemini API Key:** You need an API key for the Gemini API. You can obtain one from [Google AI Studio](https://aistudio.google.com/app/apikey). Please be aware of the pricing and usage limits associated with the Gemini API.
*   **HACS (Home Assistant Community Store):** Recommended for easy installation, though manual installation is also possible.

## Installation

### Via HACS (Recommended)

1.  **Ensure HACS is installed.** If not, follow the [HACS installation guide](https://hacs.xyz/docs/installation/prerequisites).
2.  **Add Custom Repository:**
    *   Open HACS in Home Assistant.
    *   Go to "Integrations".
    *   Click the three dots in the top right corner and select "Custom repositories".
    *   In the "Repository" field, enter the URL of this GitHub repository: `https://github.com/your_username/gemini-insights` (Replace `your_username/gemini-insights` with the actual repository URL if you forked or created it elsewhere).
    *   In the "Category" field, select "Integration".
    *   Click "Add".
3.  **Install Gemini Insights:**
    *   Search for "Gemini Insights" in HACS.
    *   Click "Install".
    *   Follow the prompts to complete the installation.
4.  **Restart Home Assistant.**

### Manual Installation

1.  **Download the latest release** from the [Releases page](https://github.com/your_username/gemini-insights/releases) of this repository (or clone the repository).
2.  **Copy the `gemini_insights` directory** (located within `custom_components`) into your Home Assistant `custom_components` directory. If the `custom_components` directory doesn't exist, create it in your main Home Assistant configuration folder.
    ```
    <config_directory>/custom_components/gemini_insights/
    ```
3.  **Restart Home Assistant.**

## Configuration

1.  **Go to Settings > Devices & Services.**
2.  Click the **"+ ADD INTEGRATION"** button in the bottom right.
3.  Search for "Gemini Insights" and click on it.
4.  **Enter your Google Gemini API Key** when prompted.
5.  Click "Submit".

Once the integration is added, you can configure its behavior:

1.  Find the "Gemini Insights" integration card in Settings > Devices & Services.
2.  Click on **"CONFIGURE"** (or "OPTIONS" if already configured).
3.  You can set the following options:
    *   **Entities to Monitor:** Select the Home Assistant entities whose data you want to send to the Gemini API.
    *   **History Period:** Choose how much historical data to include for the selected entities:
        *   `Latest Only`: Only the current state of the entities is sent (default).
        *   `1 Hour`, `6 Hours`, `12 Hours`, `24 Hours`, `3 Days`, `7 Days`: Sends significant state changes within the selected period.
        *   **Note on History Data:** Selecting longer history periods or many entities can result in large amounts of data being sent to the Gemini API. This may increase API costs, lead to longer processing times, or hit API request size limits. Use with consideration. The data sent for history includes a list of state changes (state, attributes, last_changed, last_updated).
    *   **Prompt Template:** Customize the prompt sent to the Gemini API. The placeholder `{entity_data}` will be replaced with a JSON string of the selected entities' states (and historical states, if configured).
        *   **Default Prompt:**
            ```
            Analyze the following Home Assistant data and provide:
            1. General insights based on useful observed trends.
            2. Alerts if anything looks out of the ordinary.
            3. A summary of the data for the specified entities.
            Data:
            {entity_data}
            ```
        *   **Important for reliable parsing:** The component currently tries to parse the Gemini API's response by looking for lines starting with "1. General insights", "2. Alerts", and "3. Summary". If you significantly change the prompt, ensure the API's output structure is compatible or be prepared for potential parsing issues. Ideally, future versions might support instructing Gemini to return structured JSON.
    *   **Update Interval (seconds):** How often (in seconds) to fetch data and query the Gemini API. Default is 1800 seconds (30 minutes). Be mindful of API call frequency and associated costs.

## Provided Sensors

The integration will create three sensors:

*   `sensor.gemini_insights`: Displays general insights.
*   `sensor.gemini_alerts`: Displays any alerts.
*   `sensor.gemini_summary`: Displays the summary.

Each sensor will also have attributes like `last_synced` and `raw_data` (containing the full, unparsed response from the last successful API call for that cycle, which might include all three parts if your prompt returns them together).

## Usage Examples

*   **Monitor energy consumption:** Track your smart plugs and energy monitors. With history, you can ask for trends over the past day/week, identify peak usage times, or compare current usage to historical patterns.
*   **Security overview:** Summarize door/window sensor activity and motion alerts. With 24-hour history, you can get a digest of all security-related events.
*   **Environmental comfort:** Analyze temperature, humidity, and air quality sensors. Ask for average conditions, identify periods outside desired ranges, or get summaries of fluctuations over a chosen history period.
*   **Custom daily/weekly reports:** Craft a prompt to get a specific summary of important household activities based on the historical data you've configured. For example: "Based on the last 7 days of light sensor data, what are the average times the lights turn on and off in the living room?"

## Troubleshooting

*   **"API key not valid" errors:** Double-check your Gemini API key. Ensure it's active and has the necessary permissions.
*   **Sensors show "Error fetching insights" or similar:**
    *   Check your Home Assistant logs for more detailed error messages from the `custom_components.gemini_insights` component.
    *   Verify your internet connection.
    *   Ensure the Gemini API service is operational.
    *   Your prompt might be too complex or the response too large for the model's limits. Try simplifying the prompt or reducing the number of entities.
*   **Parsing issues (insights/alerts/summary mixed up or incomplete):**
    *   The default parsing is basic. If you've heavily customized your prompt, the Gemini API might not be returning text in the expected "1. ... 2. ... 3. ..." format.
    *   Try reverting to a prompt structure similar to the default or experiment with instructing Gemini to clearly delineate sections.
    *   Check the `raw_data` attribute of one of the sensors to see the full text returned by the API.

## Contributing

Contributions are welcome! If you have ideas for improvements, new features, or bug fixes, please:

1.  Fork the repository.
2.  Create a new branch for your feature or fix.
3.  Make your changes.
4.  Submit a pull request.

Please ensure your code follows general Home Assistant development guidelines and include tests for new functionality.

## Disclaimer

*   This is a third-party custom component and is not officially supported by Home Assistant or Google.
*   Use of the Google Gemini API is subject to Google's terms of service and pricing. You are responsible for any costs incurred.
*   Always be mindful of the data you are sending to external APIs and ensure it aligns with your privacy preferences.

---

*Replace `your_username/gemini-insights` with the actual GitHub repository path throughout this README before committing.*
