import os
import json
import time
from flask import Flask, request, jsonify,render_template
from datetime import datetime
from flask_cors import CORS

# Εισαγωγή βιβλιοθηκών για scraping με Selenium και BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Δημιουργία Flask εφαρμογής
app = Flask(__name__)

# Ενεργοποίηση CORS για αιτήματα από το frontend
CORS(app)

# Δημιουργία client για το OpenAI API
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
client = OpenAI(api_key=OPENAI_API_KEY)



class WebsiteScraper:
    """
    Αντλεί περιεχόμενο κειμένου από μια ιστοσελίδα χρησιμοποιώντας Selenium για
    να χειριστεί δυναμικά φορτωμένο περιεχόμενο.
    """
    def __init__(self, url):
        self.url = url
        self.content = ""
        self.scrape_website()
    
    def setup_driver(self):
        """Ρυθμίζει τον headless Chrome driver."""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except Exception as e:
            print(f"❌ Chrome driver error: {e}")
            return None
    
    def scrape_website(self):
        """Εκτελεί το scraping της ιστοσελίδας."""
        print(f"🌐 Φορτώνω δεδομένα από: {self.url}")
        driver = self.setup_driver()
        if not driver:
            self.content = "Δεν ήταν δυνατή η πρόσβαση στην ιστοσελίδα. Fallback."
            return
        try:
            driver.get(self.url)
            time.sleep(8)  # Περιμένουμε για να φορτώσει το JavaScript
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            # Αφαίρεση μη επιθυμητών στοιχείων για καθαρό κείμενο
            for unwanted in soup(['script', 'style', 'nav', 'footer']):
                unwanted.decompose()
            text = soup.get_text()
            self.content = ' '.join(text.split())
            print(f"✅ Φόρτωσα {len(self.content)} χαρακτήρες")
        except Exception as e:
            print(f"❌ Scraping error: {e}")
            self.content = f"Σφάλμα κατά την ανάκτηση της ιστοσελίδας: {str(e)}"
        finally:
            try:
                driver.quit()
            except Exception:
                pass


def generate_chatbot_prompt(data, website_content):
    company = data.get('company', {})
    evaluation = data.get('evaluation', {})
    chatbot_style = data.get('chatbot_style', {})
    prompt = f"""
You are an expert in creating prompts for evaluation chatbots. Your job is to produce a COMPLETE system prompt for a chatbot (Chatbot B) that will be used to collect feedback from users. The prompt must be based on the following data from a form and website content.

BEFORE YOU START:
- Create evaluation questions, based on the 'Key Topics' and 'Questions' from the data. If there are not enough, supplement logically with questions related to the industry, the object, and the company description. Each question must ask for a rating on the scale {evaluation.get('rating_scale')} (e.g. 1-10) and an optional comment.
- The chatbot must ask one question at a time, wait for a response, and proceed to the next ONLY after receiving a response.
- Reactions:
  - For high rating (>80% of max, e.g. 8-10/10): Show enthusiasm (e.g. 'Great! We are excited!').
  - For medium (40-80%): Show pleasure or moderation (e.g. 'Thank you! It's good, but we can do better.').
  - For low (<40%): Show disappointment but positively (e.g. 'We are sorry you were not satisfied. Let's see how to improve.').
- Follow-up: After each response, make 1-2 follow-up questions depending on the rating:
  - High: Ask 'What did you like the most?' or 'Why this high rating?'.
  - Medium: Ask 'What could we improve slightly?' or 'Is there something specific you missed?'.
  - Low: Ask 'What was the main problem?' or 'How can we make it better next time?'.
- Goal: Collect responses from ALL 10 questions before finishing. At the end, provide a summary and export the data in JSON format.
- Use the language {chatbot_style.get('language')}, the tone {chatbot_style.get('tone')} and the personality {chatbot_style.get('personality')}.
- Start with a greeting customized to the company.
- End: After all questions, say 'Thank you!' and export JSON with: {{ "responses": [{{ "question": "...", "rating": ..., "comment": "...", "follow_up": "..." }} for each], "summary": "..." }}.

Data to base on:

---
### Company Details:
- Company Name: {company.get('name')}
- Industry: {company.get('industry')}
- Size: {company.get('size')}
- Website: {company.get('website')}
- Email: {company.get('email')}
- Description: {company.get('description')}

---
### Evaluation Details:
- Evaluation Type: {evaluation.get('type')}
- Evaluation Object: {evaluation.get('specific_object')}
- Key Topics: {', '.join(evaluation.get('key_topics', []))}
- Questions: {', '.join(evaluation.get('questions', []))}
- Rating Scale: {evaluation.get('rating_scale')}
- Comments: {evaluation.get('additional_comments_focus')}

---
### Chatbot Style:
- Language: {chatbot_style.get('language')}
- Tone: {chatbot_style.get('tone')}
- Personality: {chatbot_style.get('personality')}

---
### Website Content for Additional Information:
{website_content}

Based on ALL this, produce ONLY the final system prompt for Chatbot B. Do not add explanations – only the prompt in quoted format.
### YOU WILL WRITE THE PROMPT IN ENGLISH
"""

    return prompt


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/submit-form', methods=['POST'])
def submit_form():
    """
    Χειρίζεται την υποβολή της φόρμας, δημιουργεί prompt και καλεί το OpenAI API.
    """
    if not request.is_json:
        return jsonify({"ok": False, "error": "Απαιτούνται δεδομένα JSON."}), 400

    data = request.get_json()
    company_data = data.get('company', {})
    company_name = company_data.get('name')
    website_url = company_data.get('website')

    if not company_name:
        return jsonify({"ok": False, "error": "Το όνομα της εταιρίας είναι υποχρεωτικό."}), 400

    try:
        # 1. Ανάκτηση περιεχομένου από την ιστοσελίδα
        website_content = "Δεν δόθηκε website."
        if website_url:
            scraper = WebsiteScraper(website_url)
            website_content = scraper.content

        # 2. Δημιουργία του prompt με το περιεχόμενο της ιστοσελίδας
        prompt_text = generate_chatbot_prompt(data, website_content)

        # 3. Κλήση του OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Είσαι ένας χρήσιμος βοηθός που δημιουργεί prompts για chatbots."},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7
        )

        # 4. Αποθήκευση της απάντησης του API και των δεδομένων της φόρμας
        api_response_content = response.choices[0].message.content
        data['generated_prompt'] = api_response_content
        # Η γραμμή που αποθήκευε το scraped περιεχόμενο έχει αφαιρεθεί.

        output_dir = "chatbot_creation_results"
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company_name = "".join(c for c in company_name if c.isalnum() or c == ' ').strip().replace(' ', '_').lower()
        file_path = os.path.join(output_dir, f"chatbot_spec_{safe_company_name}_{timestamp}.json")

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 5. Επιστροφή απάντησης επιτυχίας στο frontend
        return jsonify({
            "ok": True,
            "message": "Το prompt δημιουργήθηκε και αποθηκεύτηκε με επιτυχία!",
            "file": file_path,
            "generated_prompt": api_response_content
        }), 200

    except Exception as e:
        app.logger.error(f"Σφάλμα κατά την επεξεργασία: {e}")
        return jsonify({"ok": False, "error": f"Παρουσιάστηκε σφάλμα κατά την επεξεργασία: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
