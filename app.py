from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_migrate import Migrate
import requests
from xml.etree import ElementTree as ET
from jinja2 import Template
import jenkins
import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import json
import humanize
from datetime import datetime, timedelta
from models import db, JenkinsJob 

load_dotenv()

app = Flask(__name__, static_url_path='/static')

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/jenkins_flask_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

migrate = Migrate(app, db)

# Jenkins config
JENKINS_URL = "https://f2db59331ecf85e2b4fa9a417a350e20.serveo.net"
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

        print("Git user exists")

        # Generate unique Jenkins credentials ID
        cred_id = f"git-creds-{git_user.replace('@', '_')}"

        # Create credentials dynamically
        if not create_git_credentials(git_user, git_token, cred_id):
            return "Failed to create Jenkins Git credentials."

        # Prepare Jenkins job config
        with open("job_template.xml", "r") as file:
            config_xml = file.read()

            # Replace repo-related values
            repo_name = git_repo.rstrip("/").split("/")[-1].replace(".git", "")
            config_xml = config_xml.replace("__GIT_URL__", git_repo)
            config_xml = config_xml.replace("__GIT_USER__", git_user)
            config_xml = config_xml.replace("__REPO_NAME__", repo_name)

            # Replace Jenkins config values
            config_xml = config_xml.replace("__BRANCH_NAME__", branch)
            config_xml = config_xml.replace("__GIT_CRED_ID__", cred_id)
            config_xml = config_xml.replace("__EMAIL_RECIPIENTS__", email)

            # Ensure GitHub hook trigger is included
            if "<triggers/>" in config_xml:
                config_xml = config_xml.replace(
                    "<triggers/>",
                    '''<triggers>
                        <com.cloudbees.jenkins.GitHubPushTrigger plugin="github@1.29.5">
                        <spec></spec>
                        </com.cloudbees.jenkins.GitHubPushTrigger>
                    </triggers>'''
                )


        job_name = f"job-{git_user}-{branch}".replace("/", "-")

        try:
            # Create or reconfigure job with final XML
            if server.job_exists(job_name):
                server.reconfig_job(job_name, config_xml)
            else:
                server.create_job(job_name, config_xml)

            # Trigger the Jenkins job
            server.build_job(job_name)

            # Save or update job details in the database
            existing_job = JenkinsJob.query.filter_by(job_name=job_name).first()
            if existing_job:
                existing_job.git_repo = git_repo
                existing_job.git_user = git_user
                existing_job.branch = branch
                existing_job.email = email
            else:
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

    return render_template("create_job.html")

    

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


def format_duration(ms):
    seconds = int(ms / 1000)
    minutes, sec = divmod(seconds, 60)
    hours, min_ = divmod(minutes, 60)

    if hours:
        return f"{hours} hr {min_} min"
    elif minutes:
        return f"{minutes} min {sec} sec"
    else:
        return f"{sec} sec"


@app.route('/jenkins/job-info/<job_name>/build/<build_type>', methods=['GET'])
def get_build_details(job_name, build_type):
    url = f"{JENKINS_URL}/job/{job_name}/{build_type}/api/json"
    response = requests.get(url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))
    
    if response.status_code == 200:
        data = response.json()
        print(data)
        # Fetching details
        build_details = {
            "build_number": data.get("number"),
            "status": data.get("result", "Unknown"),
            "timestamp": data.get("timestamp"),
            "duration": format_duration(data.get("duration", 0)),
            "start_time": humanize.naturaltime(datetime.now() - datetime.fromtimestamp(data.get("timestamp", 0) / 1000)),
            "started_by": next(
                (cause.get("userName") for action in data.get("actions", []) 
                if "causes" in action 
                for cause in action["causes"] 
                if "userName" in cause), 
                "Unknown"
            ),
            "revision": next(
                (action.get("lastBuiltRevision", {}).get("SHA1")
                for action in data.get("actions", [])
                if action.get("lastBuiltRevision")), 
                "N/A"
            ),
            "repository": next(
                (action.get("remoteUrls", [])[0]
                for action in data.get("actions", [])
                if "remoteUrls" in action and action.get("remoteUrls")), 
                "N/A"
            ),
            "changes": "No changes" if not data.get("changeSet", {}).get("items") else "Changes detected"
        }


        return render_template("build_details.html", job_name=job_name, build_details=build_details)
    else:
        print(response.status_code)
        return render_template("error.html", error="Failed to fetch build details")

    
# To manually trigger a Jenkins job
@app.route("/run-job/<job_name>", methods=["POST"])
def run_job(job_name):
    try:
        # Trigger the Jenkins build for the given job name
        server.build_job(job_name)

        # Redirect back to the dashboard after triggering the build
        return redirect(url_for("dashboard"))
    except Exception as e:
        return f"Failed to run job: {str(e)}"
 

@app.route("/api/jobs")
def get_jobs():
    # Fetch job names from Jenkins using the Jenkins API
    url = f"{JENKINS_URL}/api/json"
    auth = (JENKINS_USER, JENKINS_TOKEN)

    try:
        response = requests.get(url, auth=auth)
        response.raise_for_status()  # Check if the request was successful
        jobs_data = response.json()
        jobs = [job['name'] for job in jobs_data.get('jobs', [])]
        return jsonify({"jobs": jobs})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500




@app.route("/configure-tests", methods=["GET", "POST"])
def configure_tests():
    if request.method == "POST":
        job_name = request.form.get("job_name")
        test_type = request.form.get("test_type")
        test_location = request.form.get("test_location")

        print(test_type)

        if test_type == 'pytest':
            test_command = f"""
                # Create virtual environment if not exists
                if [ ! -d "jenenv" ]; then
                    python3 -m venv jenenv
                    . jenenv/bin/activate
                    pip install -U pytest
                else
                    . jenenv/bin/activate
                    python -c "import pytest" 2>/dev/null || pip install -U pytest
                fi

                # Run tests
                pytest {test_location}
                """
        elif test_type == 'unittest':
            test_command = f"python -m unittest {test_location}"
        else:
            test_command = f"echo 'Unknown test type'"

        # Get existing config
        job_url = f"{JENKINS_URL}/job/{job_name}/config.xml"
        response = requests.get(job_url, auth=(JENKINS_USER, JENKINS_TOKEN))

        if response.status_code == 200:
            root = ET.fromstring(response.text)

            # Remove existing builders
            builders = root.find("builders")
            if builders is not None:
                builders.clear()
            else:
                builders = ET.SubElement(root, "builders")

            # Add new shell command
            shell = ET.SubElement(builders, "hudson.tasks.Shell")
            command = ET.SubElement(shell, "command")
            command.text = test_command.strip()

            # Convert back to XML string
            updated_config = ET.tostring(root, encoding="unicode")

            # Update job config
            headers = {'Content-Type': 'application/xml'}
            update_response = requests.post(
                job_url,
                data=updated_config,
                auth=(JENKINS_USER, JENKINS_TOKEN),
                headers=headers
            )

            if update_response.status_code == 200:
                return "Build step updated successfully!"
            else:
                return f"Failed to update config. Error: {update_response.text}"
        else:
            return f"Failed to fetch config. Error: {response.text}"

    return render_template("configure_tests.html")


# To get list of builds with details
def get_all_builds(job_name):
    url = f"{JENKINS_URL}/job/{job_name}/api/json"
    response = requests.get(url, auth=HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN))
    if response.status_code == 200:
        data = response.json()
        builds = data.get("builds", [])
        return builds  
    return None


@app.route('/jenkins/all-builds/<job_name>', methods=['GET'])
def list_jenkins_builds(job_name):
    builds = get_all_builds(job_name)
    if builds:
        build_list = [{"build_number": build["number"], "url": f"{JENKINS_URL}/job/{job_name}/{build['number']}"} for build in builds]
        return render_template("all_builds.html", job_name=job_name, builds=build_list)
    else:
        return f"No builds found for job '{job_name}'"
    

@app.route('/jenkins/job-info/<job_name>/build/<int:build_number>/console')
def get_build_console_output(job_name, build_number):
    console_url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"

    try:
        response = requests.get(console_url, auth=(JENKINS_USER, JENKINS_TOKEN))
        response.raise_for_status()
        console_output = response.text
    except requests.RequestException as e:
        console_output = f"Error fetching console output: {str(e)}"

    return render_template(
        'console_output.html',
        job_name=job_name,
        build_number=build_number,
        console_output=console_output
    )


@app.route("/delete-job", methods=["POST"])
def delete_job():
    job_name = request.form.get("job_name")
    print(job_name)

    try:
        # Delete the Jenkins job
        if server.job_exists(job_name):
            server.delete_job(job_name)
            # Also delete the job from the database if it exists
            job_to_delete = JenkinsJob.query.filter_by(job_name=job_name).first()
            if job_to_delete:
                db.session.delete(job_to_delete)
                db.session.commit()

            return redirect(url_for("dashboard"))
        else:
            return f"Job '{job_name}' does not exist on Jenkins.", 404
    except Exception as e:
        return f"Failed to delete job: {str(e)}"





if __name__ == "__main__":
    app.run(debug=True)
