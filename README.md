# AI Insight Confidence Framework (AICF) Tool

This is a Streamlit app for generating and scoring AI-generated market research insights using the AI Insight Confidence Framework.

## What The Tool Does

The tool supports three workflows:

1. Upload survey data and an optional questionnaire. The tool generates AI-style insights and evidence notes, then scores them with AICF.
2. Upload MR-style banner table output. The tool generates insights from rows and banner columns, then scores them with AICF.
3. Upload existing AI-generated insights. The tool scores them with AICF.

The tool automatically estimates confidence across seven AICF dimensions:

- Evidence Strength
- Methodological Fit
- Triangulation / Consistency
- Interpretability
- Business Relevance
- Actionability
- Bias / Risk Control

It returns:

- Weighted confidence score
- Confidence level
- Weakest dimensions
- Recommended human review actions

## Required CSV Columns

For the "Score Existing Insights" workflow:

```text
insight_id, insight_text
```

Optional but recommended:

```text
theme, evidence_note
```

The app auto-generates the AICF dimension scores by default. If you also include manual score columns, you can choose to use them through the app checkbox:

```text
evidence_strength, methodological_fit, triangulation, interpretability, business_relevance, actionability, bias_risk
```

Manual scores should be from `1` to `5`.

## Banner Table Output Mode

For the "Generate From Tables" workflow, upload a CSV or Excel banner table output where:

- Rows contain answer attributes/options.
- Columns contain total and banner cuts such as gender, age, region, customer group, brand group, etc.
- Each table starts with a table label and question text, followed by banner headers, base row, and response rows.

Example:

```text
Table 1

Q1: Shopping Preference

,Total,Gender,,Age
,Total Respondents,Male,Female,25-34
Base: Total Respondents,100,45,55,40
Like shopping a lot,0.62,0.55,0.70,0.68
Shop only when needed,0.38,0.45,0.30,0.32
```

The app generates:

- Overall leading response insight for each table.
- Banner over-index insight.
- Banner under-index/gap insight.
- Overall summary insight.
- Complete story insight.

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy On Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload `app.py`, `aicf_framework.py`, `insight_generator.py`, `table_insight_generator.py`, `story_generator.py`, `requirements.txt`, and `README.md`.
3. Go to Streamlit Community Cloud.
4. Select the GitHub repository.
5. Set the main file path as `app.py`.
6. Deploy.

## Suggested Pilot Use

Use this app to generate and evaluate 20 to 30 AI-generated market research insights. For the pilot, first use survey data plus questionnaire to generate insights and evidence notes, then ask 3 to 5 evaluators to review or validate the generated confidence levels.
