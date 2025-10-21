import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import pandas as pd

class JiraAPI:
    def __init__(self, domain, email, token, groups):
        self.domain = domain
        self.auth = HTTPBasicAuth(email, token)
        self.header = {"Accept": "application/json", "Content-Type": "application/json"}
        self.groups = groups

    def get_active_issues(self, start_date, end_date, max_results=50, start_at=0):
        issues = []
        while True:
            query = {
                "jql": f"""
                worklogDate >= "{start_date}" AND
                worklogDate < "{end_date}"
                ORDER BY created ASC
                """,
                "maxResults": max_results,
                "startAt": start_at,
                "fields": "summary,project,worklog,customfield_10001,customfield_10035,customfield_10142,customfield_10139",
                "expand": "changelog"
            }

            url = f"{self.domain}/rest/api/3/search/jql"
            resp = requests.get(url, headers=self.header, auth=self.auth, params=query)

            try:
                resp.raise_for_status()
            except Exception as e:
                print(f"[ERROR] Jira API 回傳失敗：{e}")
                print(f"[DEBUG] 回傳內容：{resp.text}")
                raise e

            data = resp.json()
            raw_issues = data.get("issues", [])
            print(f"[INFO] 本批次取得 {len(raw_issues)} 筆 issues")

            for issue in raw_issues:
                fields = issue.get("fields", {})
                team_field = fields.get("customfield_10001")
                status_field = fields.get("customfield_10035")

                parsed = {
                    "name": fields.get("summary"),
                    "key": issue.get("key"),
                    "project_key": fields.get("project", {}).get("key"),
                    "team": team_field.get("name") if isinstance(team_field, dict) else None,
                    "status": status_field.get("value") if isinstance(status_field, dict) else None,
                    "customfield_10142": fields.get("customfield_10142"),
                    "customfield_10139": fields.get("customfield_10139")
                }

                if parsed["team"] is None:
                    print(f"[WARN] issue {parsed['key']} 缺少 team (customfield_10001)")
                if parsed["status"] is None:
                    print(f"[WARN] issue {parsed['key']} 缺少 status (customfield_10035)")

                issues.append(parsed)

            if len(raw_issues) < max_results:
                break
            start_at += max_results

        return issues


    def trace_project_info_by_issues(self, issues):
        project_grouping = {}
        for issue in issues:
            project_key = issue["project_key"]
            issue.pop("project_key")
            project_grouping.setdefault(project_key, []).append(issue)
        projects = []
        for key in project_grouping:
            info = self.get_project_info_by_key(key)
            info["issues"] = project_grouping[key]
            projects.append(info)
        return projects

    def get_project_info_by_key(self, key):
        url = f"{self.domain}/rest/api/2/project/{key}"
        resp = requests.get(url, headers=self.header, auth=self.auth)
        data = resp.json()
        return {
            "project_name": data.get("name"),
            "project_key": data.get("key"),
            "project_category": data.get("projectCategory", {}).get("name")
        }

    def get_worklog_from_issue_id(self, issue_id):
        worklogs = []
        url = f"{self.domain}/rest/api/3/issue/{issue_id}/worklog"
        resp = requests.get(url, headers=self.header, auth=self.auth)
        if resp.status_code != 200:
            return []
        for w in resp.json().get("worklogs", []):
            worklogs.append({
                "owner": w.get("author", {}).get("displayName"),
                "owner_id": w.get("author", {}).get("accountId"),
                "start_date": datetime.strptime(w["started"], "%Y-%m-%dT%H:%M:%S.%f%z").date(),
                "time_spent_hr": w["timeSpentSeconds"] / 3600
            })
        return worklogs

    def get_user_group_info_from_user_id(self, user_id):
        url = f"{self.domain}/rest/api/3/user"
        query = {"accountId": user_id, "expand": "groups"}
        resp = requests.get(url, headers=self.header, auth=self.auth, params=query)
        data = resp.json()
        user_labels = {"user_id": user_id}
        user_groups = [item["name"] for item in data.get("groups", {}).get("items", [])]
        for category, names in self.groups.items():
            for name in names:
                if name in user_groups:
                    user_labels[category] = name
        return user_labels


def project_data_to_df(projects):
    df = pd.json_normalize(projects)
    df = pd.json_normalize(df.explode("issues").to_dict(orient="records"))
    df.columns = [c.replace(".", "_") for c in df.columns]
    df.rename(columns={"issues_worklogs": "worklog"}, inplace=True)
    df = pd.json_normalize(df.explode("worklog").to_dict(orient="records"))
    df.columns = [c.replace(".", "_") for c in df.columns]
    df.rename(columns={'issues_customfield_10142': 'Parent_Key', 'issues_customfield_10139_value': 'Worklog Type'}, inplace=True)
    df = df[[c for c in df.columns if c not in ["issues", "worklog"]]]
    columns = [c for c in df.columns if c not in ["Parent_Key", "Worklog Type"]]
    return df[columns + ["Parent_Key", "Worklog Type"]]


def user_data_to_df(user_data: list[dict]) -> pd.DataFrame:
    user_data = list(user_data.values())
    df = pd.json_normalize(user_data)
    df.rename(columns={
        "user_id": "worklog_owner_id",
        "Executive Unit": "worklog_owner_EU",
        "Job Level": "worklog_owner_level",
        "Job Title": "worklog_owner_title"
    }, inplace=True)
    return df


def filter_df_by_date(df, lower_bound, upper_bound):
    return df[(df["worklog_start_date"] >= lower_bound) & (df["worklog_start_date"] < upper_bound)]
