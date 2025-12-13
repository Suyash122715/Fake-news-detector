from flask import Flask, render_template, request, redirect, url_for, session, flash
import json
import requests
import google.generativeai as genai

# --------------------------------------
# CONFIGURE GEMINI
# --------------------------------------
import os
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def run_llm(prompt):
    """
    Send any prompt to Gemini and return the response text.
    """
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    response = model.generate_content(prompt)
    return response.text.strip()


def generate_search_query(news_text):
    """
    Ask Gemini to produce a short Google search query from the user's news snippet.
    """
    prompt = f"""
    The following news headline or snippet was submitted for verification:

    "{news_text}"

    Please generate a concise Google search query that can help check whether this news is real.
    Respond ONLY with the query string, no explanations.
    """
    return run_llm(prompt)


def search_google(query):
    """
    Perform a Google Custom Search and return a list of results.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "key": "AIzaSyDodgcyKRxSmi3-m5EqW018qQP9TAWNz0Q",
        "cx": "1605f465f7b514a56",
        "num": 5
    }
    response = requests.get(url, params=params)
    data = response.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": item["title"],
            "link": item["link"],
            "snippet": item["snippet"]
        })
    return results


def check_sources(results, trusted_domains):
    """
    Check if any search result matches a trusted news domain.
    """
    for result in results:
        for domain in trusted_domains:
            if domain.lower() in result["link"].lower():
                return True
    return False


# --------------------------------------
# FLASK APP
# --------------------------------------

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Load International DB
with open(r"C:\Users\suyas\OneDrive\Desktop\IDT project\backend\venv\international_sources.json", "r", encoding="utf-8") as f:
    international_db = json.load(f)

# Load India Local DB
with open(r"C:\Users\suyas\OneDrive\Desktop\IDT project\backend\venv\local_sources.json", "r", encoding="utf-8") as f:
    india_db = json.load(f)


@app.route('/')
def login():
    return render_template('login.html')


@app.route('/signup')
def signup():
    return render_template('signup.html')


@app.route('/do_login', methods=['POST'])
def do_login():
    username = request.form.get('username')
    password = request.form.get('password')

    if username and password:
        session['user'] = username
        return redirect(url_for('home'))
    else:
        flash("Invalid login. Please try again.")
        return redirect(url_for('login'))


@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', user=session['user'])


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/how_it_works')
def how_it_works():
    return render_template('working.html')


@app.route('/search_news')
def search_news():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('select_news_type.html')


@app.route('/select_news_type', methods=['POST'])
def select_news_type():
    news_type = request.form.get('newsType')

    if news_type == "international":
        countries = [c["country"] for c in international_db["InternationalNewsSources"]]
        return render_template(
            'input.html',
            news_type="international",
            countries=countries,
            india_regions=[]
        )

    elif news_type == "india_local":
        india_regions = list(india_db["IndiaLocalNewsSources"].keys())
        return render_template(
            'input.html',
            news_type="india_local",
            countries=[],
            india_regions=india_regions
        )
    else:
        flash("Please select a valid news type.")
        return redirect(url_for('search_news'))


@app.route('/input')
def input():
    news_type = request.args.get("newsType", "international")

    if news_type == "international":
        countries = [c["country"] for c in international_db["InternationalNewsSources"]]
        india_regions = []
    else:
        countries = []
        india_regions = list(india_db["IndiaLocalNewsSources"].keys())

    return render_template(
        'input.html',
        news_type=news_type,
        countries=countries,
        india_regions=india_regions
    )


@app.route('/analyze', methods=['POST'])
def analyze():
    news_type = request.form.get('news_type')
    selected_region = request.form.get('region')
    news_text = request.form.get('newsText')

    # ------------------------------------------
    # 1. LLM generates a search query
    # ------------------------------------------
    query = generate_search_query(news_text)

    # ------------------------------------------
    # 2. Google Search
    # ------------------------------------------
    results = search_google(query)

    # ------------------------------------------
    # 3. Gather trusted sources
    # ------------------------------------------
    if news_type == "international":
        trusted_sources = []
        for item in international_db["InternationalNewsSources"]:
            if item["country"] == selected_region:
                trusted_sources = item["sources"]
                break
    elif news_type == "india_local":
        trusted_sources = india_db["IndiaLocalNewsSources"].get(selected_region, [])
    else:
        trusted_sources = []

    # ------------------------------------------
    # 4. LLM Verification against search results
    # ------------------------------------------

    # Prepare all snippets from Google
    snippets_text = "\n\n".join(
        f"- {item['title']}: {item['snippet']}"
        for item in results
    )

    # Create the prompt for Gemini
    llm_prompt = f"""
You are a fact-checking expert.

Task:
- Analyze the news headline or snippet given below and determine if it is real or fake based on the provided search results.

Instructions:
- Summarize your reasoning.
- If the news appears confirmed and consistent in the search results, explain why it is likely REAL.
- If the search results explicitly refute the news, explain why it is likely FAKE.
- If the search results are empty, irrelevant, or inconclusive, explain that it is UNKNOWN.

News to check:
"{news_text}"

Search results:
{snippets_text}

Provide a detailed explanation of your reasoning and your final verdict.
"""

    # Instead of forcing the result to just REAL/FAKE, keep the entire text
    verification_explanation = run_llm(llm_prompt)

    # ------------------------------------------
    # Save history
    # ------------------------------------------
    if 'history' not in session:
        session['history'] = []

    session['history'].append({
        'news_text': news_text,
        'news_type': news_type,
        'region': selected_region,
        'result': verification_explanation
    })

    return render_template(
        "result.html",
        result=verification_explanation,
        news_text=news_text,
        news_type=news_type,
        region=selected_region,
        search_results=results
    )


@app.route('/previous')
def previous():
    history = session.get('history', [])
    return render_template('previous.html', history=history)


if __name__ == '__main__':
    app.run(debug=True)
