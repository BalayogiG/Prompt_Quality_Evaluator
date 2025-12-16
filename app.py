import os
import random
import pandas as pd
import streamlit as st
from google import genai
from jinja2 import Template
import re
import plotly.graph_objects as go
from google.genai import types
import time

# Load environment variables
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# # Setup Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

st.set_page_config(layout="wide")

def clear_text_areas():
    for key in st.session_state.keys():
        if key.startswith("prompt_") or key.startswith("response_"):
            st.session_state[key] = ""

###########################################
# LOAD DATA
###########################################

@st.cache_data
def load_data():
    try:
        file_path = "metric_and_submetric.xlsx"
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
        except:
            df = pd.read_excel(file_path)

        df = df.fillna(method='ffill')
        df = df.dropna(how='all')

        if 'SUBMETRIC_NAME' in df.columns:
            df = df.dropna(subset=["SUBMETRIC_NAME"])
        return df

    except FileNotFoundError:
        st.error("Excel file 'metric_and_submetric.xlsx' not found!")
        return pd.DataFrame()

    except Exception as e:
        st.error(f"Error loading Excel file: {str(e)}")
        return pd.DataFrame()

df = load_data()
if df.empty:
    st.stop()

###########################################
# METRIC → SUBMETRIC MAPPING
###########################################

metric_to_submetrics = {}
for _, row in df.iterrows():
    metric_name = str(row["METRIC_NAME"]).strip()
    submetric_name = str(row["SUBMETRIC_NAME"]).strip()
    metric_to_submetrics.setdefault(metric_name, []).append(submetric_name)

###########################################
# EXPLANATION FETCHER
###########################################

def get_explanation(metric_name=None, submetric_name=None):

    if metric_name:
        row = df[df['METRIC_NAME'].str.strip() == metric_name.strip()]
        if not row.empty:
            explanation = row.iloc[0].get("METRIC_EXPLAINATION", "")
            return str(explanation).strip() if explanation else "No explanation found"
        return "Metric name not found"

    if submetric_name:
        row = df[df['SUBMETRIC_NAME'].str.strip() == submetric_name.strip()]
        if not row.empty:
            explanation = row.iloc[0].get("SUBMETRIC_EXPLAINATION", "")
            return str(explanation).strip() if explanation else "No explanation found"
        return "Submetric name not found"

    return "Please provide either a metric_name or submetric_name"

###########################################
# THREE TEMPLATES (Option A)
###########################################

single_turn_template = Template("""
You are an expert LLM and Chatbot Evaluation Specialist.

Your tasks:

1. Evaluate Suitability: Rate how well the (Prompt, Expected Response) pair tests the given Metric/Submetric. Suitability means the pair should directly align with the metric definition, be unambiguous, and sufficiently probing. 
   - Responses that are semantically equivalent to the expected response are acceptable.
   - (Format: Rating: 4/10)
2. The expected response should reflect the correct behavior of the chatbot as per the given metric/submetric.
3. If the rating is below 5, provide a detailed paragraph explaining the critical flaws that make the test case unsuitable.
4. In a separate paragraph, suggest concrete, actionable improvements to the prompt or expected response so it better tests the intended metric/submetric.
5. If the rating is >= 5, briefly note any minor limitations preventing a perfect score.

Important Notes:
- If the Expected Response is biased, incorrect, or violates the metric/submetric definition, penalize the rating severely.
- The test case is invalid if the "correct" answer is wrong.

{% if metric_exp %}Metric: {{ metric_exp }}{% endif %}
{% if submetric_exp %}Submetric: {{ submetric_exp }}{% endif %}
Prompt: {{ prompt }}
{% if response %}Expected Response: {{ response }}{% endif %}

Conversation:
Turn 1:
  User → {{ turn1.prompt }}
  Expected Bot → {{ turn1.response }}

""")


two_turn_template = Template("""
You are an expert LLM and Chatbot Evaluation Specialist.

Your tasks:

1. Evaluate Suitability: Rate how well the (Prompt, Expected Response) pair tests the given Metric/Submetric. Suitability means the pair should directly align with the metric definition, be unambiguous, and sufficiently probing. 
   - Responses that are semantically equivalent to the expected response are acceptable.
   - (Format: Rating: 4/10)
2. The expected response should reflect the correct behavior of the chatbot as per the given metric/submetric.
3. If the rating is below 5, provide a detailed paragraph explaining the critical flaws that make the test case unsuitable.
4. In a separate paragraph, suggest concrete, actionable improvements to the prompt or expected response so it better tests the intended metric/submetric.
5. If the rating is >= 5, briefly note any minor limitations preventing a perfect score.

Important Notes:
- If the Expected Response is biased, incorrect, or violates the metric/submetric definition, penalize the rating severely.
- The test case is invalid if the "correct" answer is wrong.

{% if metric_exp %}Metric: {{ metric_exp }}{% endif %}
{% if submetric_exp %}Submetric: {{ submetric_exp }}{% endif %}
Prompt: {{ prompt }}
{% if response %}Expected Response: {{ response }}{% endif %}

Conversation:
Turn 1:
  User → {{ turn1.prompt }}
  Expected Bot → {{ turn1.response }}

Turn 2:
  User → {{ turn2.prompt }}
  Expected Bot → {{ turn2.response }}
""")


three_turn_template = Template("""
You are an expert LLM and Chatbot Evaluation Specialist.

Your tasks:

1. Evaluate Suitability: Rate how well the (Prompt, Expected Response) pair tests the given Metric/Submetric. Suitability means the pair should directly align with the metric definition, be unambiguous, and sufficiently probing. 
   - Responses that are semantically equivalent to the expected response are acceptable.
   - (Format: Rating: 4/10)
2. The expected response should reflect the correct behavior of the chatbot as per the given metric/submetric.
3. If the rating is below 5, provide a detailed paragraph explaining the critical flaws that make the test case unsuitable.
4. In a separate paragraph, suggest concrete, actionable improvements to the prompt or expected response so it better tests the intended metric/submetric.
5. If the rating is >= 5, briefly note any minor limitations preventing a perfect score.

Important Notes:
- If the Expected Response is biased, incorrect, or violates the metric/submetric definition, penalize the rating severely.
- The test case is invalid if the "correct" answer is wrong.

{% if metric_exp %}Metric: {{ metric_exp }}{% endif %}
{% if submetric_exp %}Submetric: {{ submetric_exp }}{% endif %}
Prompt: {{ prompt }}
{% if response %}Expected Response: {{ response }}{% endif %}

Conversation:
Turn 1:
  User → {{ turn1.prompt }}
  Expected Bot → {{ turn1.response }}

Turn 2:
  User → {{ turn2.prompt }}
  Expected Bot → {{ turn2.response }}

Turn 3:
  User → {{ turn3.prompt }}
  Expected Bot → {{ turn3.response }}
""")


###########################################
# STREAMLIT UI
###########################################

st.markdown("<h1 style='text-align: center; font-size: 30px;'> Prompt Quality Evaluation Tool</h1>", unsafe_allow_html=True)

# SIDEBAR
with st.sidebar:
    st.header("Metric & Submetric Selection")
    metric = st.selectbox("Select Metric", list(metric_to_submetrics.keys()))
    submetric_choices = sorted(list(set(metric_to_submetrics.get(metric, []))))
    submetric = st.selectbox("Select Submetric", [""] + submetric_choices)
    conversation_type = st.selectbox("Conversation Type", ["Single Turn", "Two Turn", "Three Turn"], index=0)
    turns = 1 if conversation_type == "Single Turn" else (2 if conversation_type == "Two Turn" else 3)

# Definitions
st.markdown("<h2 style='text-align: center;'>Definitions</h2>", unsafe_allow_html=True)
col1, col2 = st.columns([3,3])

with col1:
    if metric:
        mexp = get_explanation(metric_name=metric)
        st.info(f"**Metric:** {metric}")
        st.write(mexp)

with col2:
    if submetric:
        smexp = get_explanation(submetric_name=submetric)
        st.info(f"**Submetric:** {submetric}")
        st.write(smexp)

###########################################
# Conversation Type Selector
###########################################

st.markdown("<h2 style='text-align: center;'>Conversation Input</h2>", unsafe_allow_html=True)

###########################################
# Input Fields for Turns
###########################################

inputs = []
for t in range(turns):
    st.markdown(f"### Turn {t+1}")
    c1, c2 = st.columns(2)
    with c1:
        p = st.text_area(f"User Prompt (Turn {t+1})", key=f"prompt_{t+1}", height=130)
    with c2:
        r = st.text_area(f"Expected Response (Turn {t+1})", key=f"response_{t+1}", height=130)
    inputs.append({"prompt": p, "response": r})

###########################################
# Buttons
###########################################

# Center the buttons like before
left, col1, col2, right = st.columns([1, 2, 2, 1])

with col1:
    evaluate_btn = st.button("Evaluate", type="primary", use_container_width=True)

with col2:
    clear_btn = st.button("Clear", type="secondary", use_container_width=True, on_click=clear_text_areas)

###########################################
# EVALUATION
###########################################

if evaluate_btn:

    metric_exp = get_explanation(metric_name=metric)
    submetric_exp = get_explanation(submetric_name=submetric)

    # Pick template
    if conversation_type == "Single Turn":
        template = single_turn_template
    elif conversation_type == "Two Turn":
        template = two_turn_template
    else:
        template = three_turn_template

    # Render template
    content = template.render(
        metric_exp=metric_exp,
        submetric_exp=submetric_exp,
        turn1=inputs[0],
        turn2=inputs[1] if turns >= 2 else None,
        turn3=inputs[2] if turns == 3 else None,
    )

    try:
        time.sleep(5 + random.uniform(1,5))  # slight delay to ensure UI updates before API call
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=content,
            config=types.GenerateContentConfig(
                temperature=0.3,
                top_p=0.6,
                top_k=30,
            ),
        )
        time.sleep(5)  # slight delay to ensure UI updates before rendering results

        # Extract rating
        match = re.search(r"Rating:\s*(\d+)/(\d+)", resp.text)
        if match:
            score = int(match.group(1))
            total = int(match.group(2))
            percentage = (score / total) * 100
            fig = go.Figure(
                go.Indicator(
                    mode="gauge+number",
                    value=percentage,
                    number={'suffix': "%", 'font': {'size': 18}},   # very small number font
                    title={'text': "QUALITY", 'font': {'size': 14}}, # small title font
                    gauge={
                        'axis': {
                            'range': [0, 100],
                            'tickmode': 'array',
                            'tickvals': [10, 30, 50, 70, 90],
                            'ticktext': ["VB", "Bad", "Norm", "Good", "Ex"], # shorter labels
                            'tickfont': {'size': 10}
                        },
                        'bar': {'color': "black", 'thickness': 0.2},
                        'steps': [
                            {'range': [0, 20], 'color': "firebrick"},
                            {'range': [20, 40], 'color': "orangered"},
                            {'range': [40, 60], 'color': "gold"},
                            {'range': [60, 80], 'color': "yellowgreen"},
                            {'range': [80, 100], 'color': "green"}
                        ],
                        'threshold': {
                            'line': {'color': "black", 'width': 2},
                            'thickness': 0.75,
                            'value': percentage
                        }
                    }
                )
            )

            # Compact chart size
            fig.update_layout(
                autosize=False,
                width=250,   # smaller width
                height=200,  # smaller height
                margin=dict(l=10, r=10, t=30, b=10)
            )

            st.plotly_chart(fig, use_container_width=False)
        else:
            st.warning("No rating found in text.")
        result = str(resp.text)
        lines = result.splitlines()
        reason = '\n'.join(lines[2:])
        st.text_area("Reason", value=reason, height=300, key="gemini_output")
    except Exception as e:
        st.error(f"Error calling Gemini API: {str(e)}")