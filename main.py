import os
from datetime import datetime
from io import StringIO
import pandas as pd
from flask import Flask, request
from google.cloud import storage
from jira_reporter import JiraAPI, project_data_to_df, user_data_to_df, filter_df_by_date

app = Flask(__name__)

@app.route("/", methods=["POST"])
def generate_report():
    # 讀取設定
    domain = os.environ.get("JIRA_DOMAIN", "https://nl-pmis.atlassian.net")
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_TOKEN")
    bucket_name = os.environ.get("GCS_BUCKET")

    if not email or not token or not bucket_name:
        return "Missing env vars: JIRA_EMAIL, JIRA_TOKEN, GCS_BUCKET", 500

    # 設定時間區間
    start_date = request.json.get("start_date")  # e.g. "2025-09-01"
    end_date = request.json.get("end_date")      # e.g. "2025-10-01"
    if not start_date or not end_date:
        return "Missing start_date or end_date in request JSON", 400

    print(f"[INFO] Start fetching Jira data from {start_date} to {end_date}")
    Jira = JiraAPI(domain, email, token)

    # Step 1: 抓取符合條件的 issues
    issues = Jira.get_active_issues(start_date, end_date)
    projects = Jira.trace_project_info_by_issues(issues)

    # Step 2: 抓取每筆 issue 對應的 worklog 和 user info
    user_data = {}
    for project in projects:
        for issue in project["issues"]:
            issue["worklogs"] = Jira.get_worklog_from_issue_id(issue["key"])
            for worklog in issue["worklogs"]:
                user_id = worklog.get("owner_id")
                if user_id and user_id not in user_data:
                    user_info = Jira.get_user_group_info_from_user_id(user_id)
                    user_data[user_id] = user_info

    # Step 3: 組成 dataframe 並篩選日期
    df = project_data_to_df(projects)
    user_df = user_data_to_df(user_data)
    df = pd.merge(df, user_df, on="worklog_owner_id", how="left")
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    filtered_df = filter_df_by_date(df, lower_bound=start, upper_bound=end)

    # Step 4: 輸出到 GCS
    filename = f"jiraReport_{start_date}_{end_date}.csv"
    gcs_path = f"jira-reports/{filename}"
    upload_to_gcs(bucket_name, gcs_path, filtered_df)

    return f"✅ Report uploaded to gs://{bucket_name}/{gcs_path}", 200

def upload_to_gcs(bucket_name: str, destination_blob_name: str, dataframe: pd.DataFrame):
    csv_buffer = StringIO()
    dataframe.to_csv(csv_buffer, index=False)
    csv_data = csv_buffer.getvalue()
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(csv_data, content_type='text/csv')
    print(f"[SUCCESS] Uploaded to GCS: gs://{bucket_name}/{destination_blob_name}")
