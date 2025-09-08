import yaml
import csv

# Load the YAML file
with open("data\\nlu.yml", "r", encoding="utf-8") as file:
    data = yaml.safe_load(file)

# Open a CSV file to write
with open("data\\intent_dataset.csv", "w", newline='', encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["question", "intent"])  # header

    for item in data["nlu"]:
        intent = item["intent"]
        examples = item["examples"].strip().split("\n")
        for ex in examples:
            question = ex.strip().lstrip("-").strip()
            writer.writerow([question, intent])


######################################
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

# Load dataset
df = pd.read_csv("data\\intent_dataset.csv")

# Split into train and test
X_train, X_test, y_train, y_test = train_test_split(df["question"], df["intent"], test_size=0.2, random_state=42)

# Build pipeline
# Tfidf : converts raw text to TF-IDF vectors  --> Feature Extraction
pipeline = Pipeline([
    ('tfidf', TfidfVectorizer()),   
    ('clf', LogisticRegression())
])

# Train the model
pipeline.fit(X_train, y_train)

# Evaluate
y_pred = pipeline.predict(X_test)
print("Classification Report:\n", classification_report(y_test, y_pred))

# Save model
joblib.dump(pipeline, "intent_classifier_model.pkl")

############################################


#### Testing the trained  model ########
import joblib

# Load the trained model
pipeline = joblib.load("intent_classifier_model.pkl")

# Example query
query = "I want to book a spa"
intent = pipeline.predict([query])[0]

print(f"Predicted Intent: {intent}")
#################################################
