"""Minimal Streamlit in Snowflake app for the pinky-provider live validation."""

import streamlit as st

APP_VERSION = "v1"

st.title("pinky-provider live check")
st.write(f"App version: {APP_VERSION}")
