from dotenv import load_dotenv
import os
load_dotenv()
import requests
import time
import csv
from tqdm import tqdm
import json


def login_to_tdei_system():
    tdei_username = os.environ.get('TDEI_USERNAME')
    tdei_password = os.environ.get('TDEI_PASSWORD')
    base_url = 'https://api.tdei.us'
    datasets_path = '/api/v1/datasets'
    auth_path = '/api/v1/authenticate'
    url = base_url + auth_path
    payload = {
        'username': tdei_username,
        'password': tdei_password
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, json=payload, headers=headers)
    response.json()
    access_token = response.json()['access_token']
    return access_token


def login_to_mc_system():
    mc_base_url = 'https://wa-proviso-api-dev.azurewebsites.net'
    login_path = '/auth/login'
    mc_user_name = os.environ.get('MC_USERNAME')
    mc_password = os.environ.get('MC_PASSWORD')

    # Login to the MC orchestrator
    url = mc_base_url + login_path
    payload = {
        'email': mc_user_name,
        'password': mc_password
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, json=payload, headers=headers)
    mc_access_token = response.json()['access_token']
    return mc_access_token


def add_mc_project_upload_request(updated_metadata, boundary, tdei_access_token, mc_access_token, mc_project_id):
    mc_base_url = 'https://wa-proviso-api-dev.azurewebsites.net'
    dataset_upload_api = f'/projects/{mc_project_id}/upload-tdei-dataset'
    mc_upload_request_url = mc_base_url + dataset_upload_api
    mc_tdei_upload_payload = {
    'boundary':boundary,
    'metadata': updated_metadata,
    'access_token': tdei_access_token,
    'environment' : 'prod'
    }
    request_headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer '+mc_access_token
    }
    upload_request_response = requests.post(mc_upload_request_url,json=mc_tdei_upload_payload, headers= request_headers)
    return upload_request_response


def get_project_jobs(mc_token, project_id):
    mc_base_url = 'https://wa-proviso-api-dev.azurewebsites.net'
    project_jobs_path = f'/projects/{project_id}/jobs'
    url = mc_base_url + project_jobs_path
    headers = {
        'Authorization': f'Bearer {mc_token}'
    }
    response = requests.get(url, headers=headers)
    return response.json()

def wait_for_job(mc_token, project_id, job_id):
    current_task = None
    state = None
    print(f'Waiting for job {job_id} to finish')
    while True:
        jobs = get_project_jobs(mc_token, project_id)
        job = [job for job in jobs['data'] if job['jobId'] == job_id][0]
        new_current_task = job['currentTask']
        new_state = job['state']
        if new_current_task != current_task or new_state != state:
            current_task = new_current_task
            state = new_state
            print(f'Current task: {current_task}, State: {state}')
        else:
            print(f".", end="",flush=True)
        if job['state'] == 'finished' and current_task == 'post-processing':
            return job
        time.sleep(30)

def get_new_version(old_version):
    # split the version into major, minor
    major, minor = old_version.split('.')
    # increment the patch version
    minor = str(int(minor) + 1)
    # If minor is more than 9, increment the major version
    if int(minor) > 9:
        major = str(int(major) + 1)
        minor = '0'
    # return the new version
    return f'{major}.{minor}'

def update_dataset_with_mc(tdei_dataset_id, mc_project_id, tdei_access_token, mc_access_token, county_name:str,release_notes_extra:str = ''):
    metadata, pg_id, service_id = get_tdei_dataset_metadata(tdei_dataset_id,tdei_access_token)
    print(metadata['dataset_detail']['version'])
    new_tdei_version = get_new_version(metadata['dataset_detail']['version'])
    new_metadata = get_new_metadata(county_name)
    print(new_metadata['dataset_detail']['version'])
    new_metadata['dataset_detail']['version'] = new_tdei_version
    new_boundary_geojson = new_metadata['dataset_detail']['dataset_area']
    new_boundary = new_boundary_geojson['features'][0]
    if not new_boundary['properties']:
        new_boundary['properties'] = {}
    new_boundary['properties']['name'] = f'{county_name} ui'
    new_boundary['properties']['id'] = mc_project_id
    new_boundary['properties']['tdei_service_id'] = service_id
    new_boundary['properties']['tdei_pg_id'] = pg_id
    upload_request_response = add_mc_project_upload_request(new_metadata, new_boundary, tdei_access_token, mc_access_token, mc_project_id)
    if upload_request_response.status_code == 200:
        print('Upload request added successfully')
        print(upload_request_response.json())
        flow_id = upload_request_response.json()['flow_id']
        job = wait_for_job(mc_access_token, mc_project_id, flow_id)
        if job['state'] == 'finished':
            print('Job finished successfully')
        else:
            print('Job failed')
    else:
        print('Error: Upload request not added')
        print(upload_request_response.json())
    



def get_tdei_dataset_metadata(tdei_dataset_id, tdei_access_token):
    url = f'https://api.tdei.us/api/v1/datasets?'
    url += 'page_no=1&page_size=10&sort_field=uploaded_timestamp&sort_order=DESC&status=All&'
    url += f'tdei_dataset_id={tdei_dataset_id}&'
    url += 'tdei_project_group_id=1dd7c38e-c7a6-4e3a-be8b-379f823a7ad7'
    response = requests.get(url, headers={'Authorization': 'Bearer ' + tdei_access_token})
    data = response.json()
    if len(data) > 0:
        dataset = data[0]
        project_group = dataset['project_group']['tdei_project_group_id']
        service_id = dataset['service']['tdei_service_id']
        metadata = dataset['metadata']
        return metadata, project_group, service_id
    else:
        print('Dataset not found')
        return None, None, None



def get_new_metadata(county_name:str):
    file_path = f'ui-union/metadata_new/{county_name}.json' 
    if not os.path.exists(file_path):
        print(f'File path {file_path} does not exist')
        return None
    with open(file_path,'r') as f:
        metadata = json.load(f)
    return metadata



def parse_and_update(tdei_dataset_id, mc_project_id, county_name):
    tdei_access_token = login_to_tdei_system()
    mc_access_token = login_to_mc_system()
    update_dataset_with_mc(tdei_dataset_id,mc_project_id,tdei_access_token,mc_access_token,county_name)


def parse_csv(file_path:str):
    parsed_rows = []
    with open(file_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            county_name = row[0]
            mc_project_id = row[1]
            tdei_dataset_id = row[2]
            # update_dataset_with_mc(tdei_dataset_id, mc_project_id)
            print(f'Updating dataset for {county_name.capitalize()} County')
            parse_and_update(tdei_dataset_id,mc_project_id,county_name)

            parsed_rows.append((tdei_dataset_id, mc_project_id,county_name))
    return parsed_rows    

if __name__ == '__main__':
    # tdei_access_token = login_to_tdei_system()
    # mc_access_token = login_to_mc_system()
    # update_dataset_with_mc('d98054b1-63c0-42b7-849a-dded14b18977','67650e2bc5ea03428d2cf840',tdei_access_token,mc_access_token,'asotin')
    parse_csv('ui-union/work.csv')

    # main('tdei_access_token', 'mc_access_token')
    
        