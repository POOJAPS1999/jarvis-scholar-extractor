"""
auth.py
=======
Login / sign-up gate for the Jarvis Scholar dashboard. Every page calls
require_login() right after set_page_config + THEME_CSS; until the user is
authenticated, the page renders the auth screen and stops.

Real password accounts (verified by the Phase 1 backend at /auth/signup and
/auth/login). Auth state lives in st.session_state for the browser session
(a refresh asks the user to log in again — acceptable for a research tool;
no cookies/components needed).
"""
from __future__ import annotations

import os

import requests
import streamlit as st

try:
    _secret_url = st.secrets.get("API_BASE_URL")
except Exception:
    _secret_url = None
API_BASE_URL = (
    _secret_url
    or os.environ.get("JARVIS_API_URL")
    or "https://jarvis-scholar-extractor-production.up.railway.app"
).rstrip("/")

_ROLES = ["Faculty", "PhD scholar", "Postdoctoral researcher", "Researcher / Scientist",
          "Student (Master's)", "Student (Bachelor's)", "Librarian / Information specialist",
          "Clinician", "Other"]

_SESSION_KEY = "js_auth_user"


def current_user():
    return st.session_state.get(_SESSION_KEY)


def logout():
    st.session_state.pop(_SESSION_KEY, None)


def _api_post(path, payload):
    r = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=30)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(detail)
    return r.json()


def _auth_screen():
    st.markdown(
        "<div style='max-width:560px;margin:6px auto 0;'>"
        "<div style='font-family:\"Segoe UI\",sans-serif;font-size:1.7rem;font-weight:800;color:#12283b;'>"
        "Welcome to Jarvis Scholar</div>"
        "<div style='color:#4a627a;font-family:Georgia,serif;margin-top:2px;'>"
        "Please sign in or create an account to use the bibliometric console.</div></div>",
        unsafe_allow_html=True,
    )
    st.write("")
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        tab_login, tab_signup = st.tabs(["Log in", "Create account"])

        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="you@institution.edu")
                pw = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
            if submitted:
                if not email or not pw:
                    st.error("Enter your email and password.")
                else:
                    try:
                        user = _api_post("/auth/login", {"email": email, "password": pw})
                        st.session_state[_SESSION_KEY] = user
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        with tab_signup:
            with st.form("signup_form"):
                c1, c2 = st.columns(2)
                first = c1.text_input("First name")
                last = c2.text_input("Last name")
                institution = st.text_input("Institution / organisation")
                c3, c4 = st.columns(2)
                role = c3.selectbox("You are a…", _ROLES)
                designation = c4.text_input("Designation / title",
                                            placeholder="e.g. Assistant Professor")
                email_s = st.text_input("Email", key="su_email", placeholder="you@institution.edu")
                pw1 = st.text_input("Password (min 6 characters)", type="password", key="su_pw")
                pw2 = st.text_input("Confirm password", type="password", key="su_pw2")
                agree = st.checkbox("I agree my details may be stored for access and updates.")
                submitted_s = st.form_submit_button("Create account & enter", type="primary",
                                                    use_container_width=True)
            if submitted_s:
                if not (first and last and institution and designation and email_s and pw1):
                    st.error("Please fill in every field.")
                elif pw1 != pw2:
                    st.error("Passwords don't match.")
                elif len(pw1) < 6:
                    st.error("Password must be at least 6 characters.")
                elif not agree:
                    st.error("Please tick the consent box to continue.")
                else:
                    try:
                        user = _api_post("/auth/signup", {
                            "email": email_s, "password": pw1, "name": first, "last_name": last,
                            "institution": institution, "role": role, "designation": designation})
                        st.session_state[_SESSION_KEY] = user
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.caption("Your details are used for access and product updates. "
                   "We don't share them with third parties.")


def require_login():
    """Gate: if not logged in, show the auth screen and stop the page."""
    if current_user():
        return
    _auth_screen()
    st.stop()


def sidebar_account():
    """Small account box + log-out button in the sidebar (call after login)."""
    u = current_user()
    if not u:
        return
    with st.sidebar:
        st.markdown(
            f"<div style='padding:8px 10px;border:1px solid #d6e3f2;border-radius:10px;background:#fff;'>"
            f"<div style='font-weight:700;color:#12283b;font-family:\"Segoe UI\",sans-serif;'>"
            f"{u.get('name','')} {u.get('last_name','')}</div>"
            f"<div style='color:#4a627a;font-size:.8rem;'>{u.get('email','')}</div></div>",
            unsafe_allow_html=True,
        )
        if st.button("Log out", use_container_width=True, key="js_logout"):
            logout()
            st.rerun()
