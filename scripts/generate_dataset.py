"""
Generate a realistic loan-application dataset.

The schema mirrors the widely used "Loan Prediction" dataset
(Loan_ID, Gender, Married, Dependents, Education, Self_Employed,
ApplicantIncome, CoapplicantIncome, LoanAmount, Loan_Amount_Term,
Credit_History, Property_Area, Loan_Status) so the real CSV can be dropped
into data/loan_data.csv without any code changes.

Missing values are injected on purpose so the preprocessing pipeline
(imputation + encoding) has real work to do.

Usage:
    python scripts/generate_dataset.py            # writes data/loan_data.csv
    python scripts/generate_dataset.py -n 1000 -o data/big.csv
"""
import argparse
import os

import numpy as np
import pandas as pd


def generate(n: int = 614, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    gender = rng.choice(["Male", "Female"], n, p=[0.81, 0.19])
    married = rng.choice(["Yes", "No"], n, p=[0.65, 0.35])
    dependents = rng.choice(["0", "1", "2", "3+"], n, p=[0.57, 0.17, 0.17, 0.09])
    education = rng.choice(["Graduate", "Not Graduate"], n, p=[0.78, 0.22])
    self_emp = rng.choice(["No", "Yes"], n, p=[0.86, 0.14])
    area = rng.choice(["Semiurban", "Urban", "Rural"], n, p=[0.38, 0.33, 0.29])

    # Monthly incomes (INR); graduates and self-employed earn a little more
    base = rng.lognormal(mean=8.25, sigma=0.55, size=n)
    base *= np.where(education == "Graduate", 1.18, 0.85)
    base *= np.where(self_emp == "Yes", 1.15, 1.0)
    applicant_income = np.round(np.clip(base, 150, 81000))

    has_co = rng.random(n) < np.where(married == "Yes", 0.70, 0.30)
    co_income = np.where(has_co, rng.lognormal(7.5, 0.6, n), 0.0)
    co_income = np.round(np.clip(co_income, 0, 42000))

    total_income = applicant_income + co_income

    # Loan amount in thousands of INR, loosely tied to income
    loan_amount = 40 + 0.022 * total_income + rng.normal(0, 35, n)
    loan_amount = np.round(np.clip(loan_amount, 9, 700))

    term = rng.choice([360, 180, 480, 300, 240, 120, 84, 60, 36, 12], n,
                      p=[0.85, 0.07, 0.025, 0.02, 0.01, 0.01, 0.006, 0.004, 0.003, 0.002])
    credit = rng.choice([1.0, 0.0], n, p=[0.85, 0.15])

    # Approval logic: credit history dominates, then affordability
    emi = (loan_amount * 1000) / term                       # rough monthly instalment
    burden = emi / np.maximum(total_income, 1)               # share of income going to EMI
    logit = (
        -2.5
        + 3.6 * credit
        + 0.55 * (area == "Semiurban")
        - 0.35 * (area == "Rural")
        + 0.35 * (married == "Yes")
        + 0.25 * (education == "Graduate")
        - 4.5 * np.clip(burden - 0.12, 0, None)
        + 0.15 * np.log1p(total_income / 5000)
    )
    prob = 1 / (1 + np.exp(-logit))
    status = np.where(rng.random(n) < prob, "Y", "N")

    df = pd.DataFrame({
        "Loan_ID": [f"LP{100000 + i:06d}" for i in range(n)],
        "Gender": gender,
        "Married": married,
        "Dependents": dependents,
        "Education": education,
        "Self_Employed": self_emp,
        "ApplicantIncome": applicant_income.astype(int),
        "CoapplicantIncome": co_income,
        "LoanAmount": loan_amount,
        "Loan_Amount_Term": term.astype(float),
        "Credit_History": credit,
        "Property_Area": area,
        "Loan_Status": status,
    })

    # Inject missing values (similar counts to the public dataset)
    missing = {
        "Gender": 13, "Married": 3, "Dependents": 15, "Self_Employed": 32,
        "LoanAmount": 22, "Loan_Amount_Term": 14, "Credit_History": 50,
    }
    scale = n / 614
    for col, k in missing.items():
        idx = rng.choice(n, size=max(1, int(k * scale)), replace=False)
        df[col] = df[col].astype(object)
        df.loc[idx, col] = np.nan
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-n", type=int, default=614, help="number of rows")
    ap.add_argument("--seed", type=int, default=42)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("-o", default=os.path.join(root, "data", "loan_data.csv"))
    args = ap.parse_args()

    df = generate(args.n, args.seed)
    os.makedirs(os.path.dirname(args.o), exist_ok=True)
    df.to_csv(args.o, index=False)
    print(f"Wrote {len(df)} rows to {args.o}")
    print(f"Approval rate: {(df['Loan_Status'] == 'Y').mean():.1%}")
    print("Missing values:\n" + df.isna().sum()[df.isna().sum() > 0].to_string())


if __name__ == "__main__":
    main()
