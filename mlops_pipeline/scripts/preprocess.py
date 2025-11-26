import argparse
import os
import pandas as pd
from sklearn.model_selection import train_test_split

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-data", type=str, default="/opt/ml/processing/input")
    args = parser.parse_args()

    input_file = os.path.join(args.input_data, "real_estate.csv")
    print(f"Reading data from {input_file}")
    df = pd.read_csv(input_file)

    if "No" in df.columns:
        print("Dropping 'No' column")
        df = df.drop(columns=["No"])

    train, test = train_test_split(df, test_size=0.2, random_state=42)

    os.makedirs("/opt/ml/processing/train", exist_ok=True)
    os.makedirs("/opt/ml/processing/test", exist_ok=True)

    train.to_csv("/opt/ml/processing/train/train.csv", index=False, header=False)
    test.to_csv("/opt/ml/processing/test/test.csv", index=False, header=False)

    print("Preprocessing completed.")