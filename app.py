import os
import pandas as pd
import streamlit as st
from google import genai
from jinja2 import Template
import re
import plotly.graph_objects as go

# Load environment variables
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# # Setup Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

st.set_page_config(layout="wide")

def clear_text_areas():
    st.session_state.prompt_input = ""
    st.session_state.response_input = ""

# --- Load Excel file ---
@st.cache_data
def load_data():
    try:
        file_path = "metric_and_submetric.xlsx"
        
        # Try reading with different options to handle merged cells better
        try:
            # First attempt: use openpyxl engine which handles merged cells better
            df = pd.read_excel(file_path, engine='openpyxl')
        except:
            # Fallback: use default engine
            df = pd.read_excel(file_path)
        
        # Handle merged cells by forward-filling ALL columns
        # This is more aggressive but should handle most merged cell scenarios
        df = df.fillna(method='ffill')
        
        # Remove completely empty rows
        df = df.dropna(how='all')
        
        # Only keep rows where submetric name exists (assuming this is always filled)
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

# Build metric -> submetric mapping
metric_to_submetrics = {}
for _, row in df.iterrows():
    # Handle potential NaN values after forward-fill
    metric_name = str(row["METRIC_NAME"]).strip() if pd.notna(row["METRIC_NAME"]) else "Unknown"
    submetric_name = str(row["SUBMETRIC_NAME"]).strip() if pd.notna(row["SUBMETRIC_NAME"]) else "Unknown"
    
    if metric_name != "Unknown" and submetric_name != "Unknown":
        metric_to_submetrics.setdefault(metric_name, []).append(submetric_name)

# Function to get explanations
def get_explanation(metric_name=None, submetric_name=None):
    """
    Returns the explanation for a given metric_name or submetric_name.
    """
    if metric_name:
        row = df[df['METRIC_NAME'].str.strip() == metric_name.strip()]
        if not row.empty:
            explanation_cols = ['METRIC_EXPLAINATION']
            for col in explanation_cols:
                if col in df.columns:
                    explanation = row.iloc[0].get(col, "")
                    if pd.notna(explanation) and str(explanation).strip():
                        return str(explanation).strip()
            return "No explanation found"
        else:
            return "Metric name not found"
    
    if submetric_name:
        row = df[df['SUBMETRIC_NAME'].str.strip() == submetric_name.strip()]
        if not row.empty:
            explanation_cols = ['SUBMETRIC_EXPLAINATION']
            for col in explanation_cols:
                if col in df.columns:
                    explanation = row.iloc[0].get(col, "")
                    if pd.notna(explanation) and str(explanation).strip():
                        return str(explanation).strip()
            return "No explanation found"
        else:
            return "Submetric name not found"
    
    return "Please provide either a metric_name or submetric_name"

# Jinja template
## bala's initial system prompt
# prompt_template = Template("""
# You are an LLM/Chatbot evaluation expert.

# Your tasks:

# 1.  Rate the suitability of the prompt-response pair for evaluating the chatbot on the given (sub-)metric, on a 0-10 scale. Suitability means how effectively the pair can reveal performance on that metric in the given domain. This evaluation has to be rigorous and ensure high quality. (Give in this format Rating: 4/10)
# 2.  If the rating is below 5, provide a detailed paragraph explaining why it is unsuitable. 
# 3.  In a separate paragraph, suggest concrete tips to improve the prompt so it better tests the metric.
# 4.  (Optional) If the rating is >= 5, you may briefly note any minor limitations affecting the score.

# {% if metric_exp %}Metric Explanation: {{ metric_exp }}{% endif %}
# {% if submetric_exp %}Submetric Explanation: {{ submetric_exp }}{% endif %}
# Prompt: {{ prompt }}
# {% if response %}Response: {{ response }}{% endif %}
# """)


## test by shashank
prompt_template = Template("""
You are an expert LLM and Chatbot Evaluation Specialist.

Your tasks:

1. Evaluate Suitability: Rate how well the (Prompt, Expected Response) pair tests the given Metric/Submetric. Suitability means the pair should directly align with the metric definition, be unambiguous, and sufficiently probing. (Format: Rating: 4/10)
2. If the rating is below 5, provide a detailed paragraph explaining the critical flaws that make the test case unsuitable.
3. In a separate paragraph, suggest concrete, actionable improvements to the prompt or expected response so it better tests the intended metric.
4. (Optional) If the rating is >= 5, you may briefly note any minor limitations preventing a perfect score.

Important Notes:
- If the Expected Response is biased, incorrect, or violates the metric definition, penalize the rating severely.
- The test case is invalid if the "correct" answer is wrong.

{% if metric_exp %}Metric: {{ metric_exp }}{% endif %}
{% if submetric_exp %}Submetric: {{ submetric_exp }}{% endif %}
Prompt: {{ prompt }}
{% if response %}Expected Response: {{ response }}{% endif %}
""")


# --- Streamlit UI ---
st.markdown("<h1 style='text-align: center; font-size: 30px;'> Prompt Quality Evaluation Tool</h1>", unsafe_allow_html=True)

# Check if data is loaded
if not metric_to_submetrics:
    st.error("No valid data found in the Excel file.")
    st.stop()

# Left sidebar for selections
with st.sidebar:
    st.header("Metric and Submetric Selection")
    
    # Metric selection
    metric = st.selectbox("Select Metric", list(metric_to_submetrics.keys()), key="metric_select")
    
    # Submetric selection
    submetric_choices = list(set(metric_to_submetrics.get(metric, [])))  # Remove duplicates
    submetric_choices.sort()  # Optional: sort alphabetically for better UX
    submetric = st.selectbox("Select Submetric", [""] + submetric_choices, key="submetric_select")

# Main content area
st.markdown("<h1 style='text-align: center; font-size: 20px;'>Definitions</h1>", unsafe_allow_html=True)

# Two-column layout for explanations
exp_col1, exp_col2 = st.columns([3,3])

with exp_col1:
    if metric:
        metric_explanation = get_explanation(metric_name=metric)
        st.info(f"**Metric:** {metric}")
        st.write(metric_explanation)

with exp_col2:
    if submetric:
        submetric_explanation = get_explanation(submetric_name=submetric)
        st.info(f"**Submetric:** {submetric}")
        st.write(submetric_explanation)

# Input section
st.markdown("<h1 style='text-align: center; font-size: 20px;'> Input Prompt and Response</h1>", unsafe_allow_html=True)

# Two-column layout for input fields
input_col1, input_col2 = st.columns([2, 2])

with input_col1:
    prompt = st.text_area("Enter Prompt", height=200, key="prompt_input")

with input_col2:
    response = st.text_area("Enter Response", height=200, key="response_input")

# Center the evaluate button
left, col1, col2, right = st.columns([1, 2, 2, 1])

with col1:
    evaluate_btn = st.button("Evaluate", type="primary", use_container_width=True)
with col2:
    clear_btn = st.button("Clear", type="secondary", use_container_width=True, on_click=clear_text_areas)

if evaluate_btn:
    if not prompt.strip():
        st.warning("Please enter a prompt before evaluating.")
    else:
        # Get explanations for template
        metric_exp = get_explanation(metric_name=metric) if metric else None
        submetric_exp = get_explanation(submetric_name=submetric) if submetric else None
        
        # Only include valid explanations (not error messages)
        if metric_exp and ("not found" in metric_exp or "Please provide" in metric_exp):
            metric_exp = None
        if submetric_exp and ("not found" in submetric_exp or "Please provide" in submetric_exp):
            submetric_exp = None
            
        contents = prompt_template.render(
            metric_exp=metric_exp,
            submetric_exp=submetric_exp,
            prompt=prompt,
            response=response if response.strip() else None
        )
        
        # Tabs for different outputs
        st.tabs(["Results"])
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents
            )
            # --- Extract rating using regex ---
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
