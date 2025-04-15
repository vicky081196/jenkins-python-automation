from flask import Flask, render_template, request, jsonify
from flask_migrate import Migrate
import jenkins
import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import json
import humanize
from datetime import datetime
from models import db, JenkinsJob 

load_dotenv()

app = Flask(__name__, static_url_path='/static')

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/jenkins_flask_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

migrate = Migrate(app, db)

# Jenkins config
JENKINS_URL = "https://b384065a84ddd646c4a2bfd44d1ee69d.serveo.net"
JENKINS_USER = os.getenv("JENKINS_USERNAME")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")

server = jenkins.Jenkins(JENKINS_URL, username=JENKINS_USER, password=JENKINS_TOKEN)


@app.route("/", methods=["GET"])
def dashboard():
    # Fetch all Jenkins jobs from the database
    jobs = JenkinsJob.query.all()

    return render_template("dashboard.html", jobs=jobs)


# Helper to create Git credentials
def create_git_credentials(git_user, git_token, cred_id):
    session = requests.Session()

    # Get CSRF crumb
    crumb_url = f"{JENKINS_URL}/crumbIssuer/api/json"
    crumb_response = session.get(crumb_url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))

    if crumb_response.status_code != 200:
        return False

    crumb_data = crumb_response.json()
    headers = {
        "Content-Type": "application/json",
        crumb_data["crumbRequestField"]: crumb_data["crumb"]
    }

    creds_url = f"{JENKINS_URL}/credentials/store/system/domain/_/createCredentials"
    payload = {
        "": "0",
        "credentials": {
            "scope": "GLOBAL",
            "id": cred_id,
            "username": git_user,
            "password": git_token,
            "description": f"Auto-created for {git_user}",
            "$class": "com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl"
        }
    }

    response = session.post(
        creds_url,
        data={
            "json": json.dumps(payload)
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            crumb_data["crumbRequestField"]: crumb_data["crumb"]
        },
        auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN)
    )

    print("STATUS:", response.status_code)
    print("RESPONSE TEXT:", response.text)

    return response.status_code in [200, 201, 204]


@app.route("/create_job", methods=["GET", "POST"])
def create_job():
    if request.method == "POST":
        git_repo = request.form["git_repo"]
        git_user = request.form["git_user"]
        git_token = request.form["git_token"]
        branch = request.form["branch"]
        email = request.form["email"]

        # Validate GitHub username
        github_user_check = requests.get(f"https://api.github.com/users/{git_user}")
        if github_user_check.status_code != 200:
            return f"GitHub user '{git_user}' not found. Please enter a valid GitHub username."
        else:
            print("Git user exists")


        # Generate unique Jenkins credentials ID
        cred_id = f"git-creds-{git_user.replace('@', '_')}"

        # Create credentials dynamically
        if not create_git_credentials(git_user, git_token, cred_id):
            return "Failed to create Jenkins Git credentials."

        # Prepare Jenkins job config
        with open("job_template.xml", "r") as file:
            config_xml = file.read()
            config_xml = config_xml.replace("__GIT_URL__", git_repo)
            config_xml = config_xml.replace("__BRANCH_NAME__", branch)
            config_xml = config_xml.replace("__GIT_CRED_ID__", cred_id)

        job_name = f"job-{git_user}-{branch}".replace("/", "-")

        try:
            # Check if the job exists in Jenkins, if it does, reconfigure it, otherwise create it
            if server.job_exists(job_name):
                server.reconfig_job(job_name, config_xml)
            else:
                server.create_job(job_name, config_xml)

            # Trigger the Jenkins job
            server.build_job(job_name)

            # Save or update job details in the database
            existing_job = JenkinsJob.query.filter_by(job_name=job_name).first()

            if existing_job:
                # Update existing job record
                existing_job.git_repo = git_repo
                existing_job.git_user = git_user
                existing_job.branch = branch
                existing_job.email = email
            else:
                # Insert new job record
                new_job = JenkinsJob(
                    job_name=job_name,
                    git_repo=git_repo,
                    git_user=git_user,
                    branch=branch,
                    email=email
                )
                db.session.add(new_job)

            db.session.commit()


            return f"Jenkins job '{job_name}' created and triggered, and job details saved to the database!"
        except Exception as e:
            return f"Failed: {str(e)}"

    return render_template("index.html")


# @app.route('/jenkins/job-info/<job_name>', methods=['GET'])
# def get_jenkins_job_info(job_name):
#     url = f"{JENKINS_URL}/job/{job_name}/lastBuild/api/json"
#     response = requests.get(url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))
#     response.raise_for_status()

#     if response.status_code == 200:
#         data = response.json()
#         job_info = {
#             "job_name": job_name,
#             "build_number": data.get("number"),
#             "status": data.get("result"),
#             "building": data.get("building"),
#             "timestamp": data.get("timestamp"),
#             "duration": data.get("duration"),
#             "url": data.get("url"),
#             "branch": data.get("actions", [{}])[0].get("parameters", [{}])[0].get("value", "N/A")
#         }
#         return render_template("job_info.html", job_info=job_info)
#     else:
#         return render_template("error.html", error="Failed to fetch job info")
    

@app.template_filter('datetimeformat')
def datetimeformat(value):
    dt = datetime.fromtimestamp(value / 1000)  # divide by 1000 if value is in ms
    return humanize.naturaltime(datetime.now() - dt)
    
def get_build_summary(job_name, build_type):
    url = f"{JENKINS_URL}/job/{job_name}/{build_type}/api/json"
    response = requests.get(url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))
    if response.status_code == 200:
        data = response.json()
        return {
            "build_number": data.get("number"),
            "timestamp": data.get("timestamp")
        }
    return None

@app.route('/jenkins/job-info/<job_name>', methods=['GET'])
def get_jenkins_job_info(job_name):
    build_types = [
        "lastBuild",
        "lastStableBuild",
        "lastSuccessfulBuild",
        "lastFailedBuild",
        "lastUnsuccessfulBuild",
        "lastCompletedBuild"
    ]
    
    build_summaries = {}
    for btype in build_types:
        info = get_build_summary(job_name, btype)
        if info:
            info["type"] = btype  # useful for labeling
            build_summaries[btype] = info
    print(build_summaries)


    return render_template("job_info.html", job_name=job_name, builds=build_summaries)


@app.route('/jenkins/job-info/<job_name>/build/<build_type>', methods=['GET'])
def get_build_details(job_name, build_type):
    url = f"{JENKINS_URL}/job/{job_name}/{build_type}/api/json"
    response = requests.get(url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))
    
    if response.status_code == 200:
        data = response.json()
        print(data)
        # Fetching details
        build_details = {
            "status": data.get("result", "Unknown"),
            "timestamp": data.get("timestamp"),
            "duration": data.get("duration"),
            "started_by": data.get("actions", [{}])[0].get("causes", [{}])[0].get("userName", "Unknown"),
            "start_time": humanize.naturaltime(datetime.now() - datetime.fromtimestamp(data.get("timestamp", 0) / 1000)),
            "revision": data.get("actions", [{}])[2].get("buildsByBranchName", {}).get("refs/remotes/origin/main", {}).get("revision", "N/A"),
            "repository": data.get("actions", [{}])[2].get("scm", {}).get("url", "N/A"),
            "changes": "No changes" if not data.get("changeSet", {}).get("items") else "Changes detected"
        }

        return render_template("build_details.html", job_name=job_name, build_details=build_details)
    else:
        print(response.status_code)
        return render_template("error.html", error="Failed to fetch build details")

    
    



if __name__ == "__main__":
    app.run(debug=True)
