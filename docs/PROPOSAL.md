# Project Proposal: Loan Approval Predictor

**Course:** 21CSE216P – Linux and Container Technologies (Capstone Project)
**Student:** Pranay Jain · RA2411003011032 · CSE Core, Section P1
**Institution:** SRM Institute of Science and Technology, Kattankulathur

## Problem statement
Banks receive many loan applications and must decide quickly and consistently whether to approve each one. The goal is a small application that **predicts whether a loan application will be approved**, based on applicant details such as income, credit history and loan amount. It must then be packaged and run as containers using Podman.

## Objectives
1. Load applicant data (income, credit history, loan amount, education, property area, …).
2. Handle missing values and encode categorical columns.
3. Train a Decision Tree and a Logistic Regression model and report accuracy, along with precision, recall, F1 and the confusion matrix.
4. Predict approval for new applicants through an interactive web interface and a REST API, and store every prediction.
5. Containerise the application with a custom Containerfile and image, and run it with Podman. The deployment must use a user-defined network, persistent storage (volumes and bind mounts) and port mapping.
6. Demonstrate the container lifecycle (build, run, inspect, logs, stop/start, remove), version the image, and push and pull it through a public registry.

## Proposed solution
A two-tier containerised web application:
- **`loan-app`:** a custom image (Python 3.12-slim) running Flask under gunicorn. It serves the web UI (predict, dashboard, history, batch upload, model lab, dataset view) and a REST API, and uses scikit-learn pipelines for preprocessing and modelling.
- **`loan-db`:** PostgreSQL 16 storing the prediction history.
- Both containers join the Podman bridge network **`loan-net`**, and the app reaches the database by name.
- Prediction history lives on volume **`loan-pgdata`** and trained models on **`loan-models`**. The dataset and log files are bind-mounted from the host.
- Only the app is published to the host (**`-p 8080:5000`**).

## Tools and technologies
| Area | Tools |
|---|---|
| OS / containers | Linux, Podman (rootless), Containerfile, Podman networks and volumes, quay.io / Docker Hub |
| Backend | Python 3.12, Flask, gunicorn |
| Machine learning | scikit-learn (DecisionTreeClassifier, LogisticRegression, SimpleImputer, OneHotEncoder), pandas, NumPy |
| Database | PostgreSQL 16 (SQLite for local development) |
| Frontend | HTML5, CSS3, JavaScript (SVG charts) |
| Testing / DevOps | pytest, Git and GitHub, GitHub Actions |

## Expected outcome
A working, interactive loan-approval web app that anyone can start with two commands (`./podman/build.sh && ./podman/up.sh`). It will report model accuracy, explain each decision, keep its data across container restarts, and be published as a public container image.
