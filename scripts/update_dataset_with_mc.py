from dotenv import load_dotenv
import os
load_dotenv()
import requests
import time
import csv
from tqdm import tqdm


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
    while True:
        print(f'Waiting for job {job_id} to finish')
        jobs = get_project_jobs(mc_token, project_id)
        job = [job for job in jobs['data'] if job['jobId'] == job_id][0]
        current_task = job['currentTask']
        state = job['state']
        print(f'Current task: {current_task}, State: {state}')
        if job['state'] == 'finished' and current_task == 'post-processing':
            return job
        time.sleep(30)



def update_dataset_with_mc(tdei_dataset_id, mc_project_id, tdei_access_token, mc_access_token, hxgn_fix: bool = True):
    if tdei_access_token:
        print(f'TDEI Logged in')
    if mc_access_token:
        print(f'MC Logged in')
    metadata, project_group, service_id = get_tdei_dataset_metadata(tdei_dataset_id, tdei_access_token)
    if metadata is None or project_group is None or service_id is None:
        print('Error: Metadata not found, project group not found or service id not found')
        return
    existing_version = metadata['dataset_detail']['version']    
    name = metadata['dataset_detail']['name']
    new_version = get_new_version(existing_version)
    print(name)
    print(f'Old version {existing_version}, New version {new_version}')
        
    boundary = metadata['dataset_detail']['dataset_area']
    # Get the feature[0] as boundary
    if boundary['features']:
        boundary = boundary['features'][0]
    else:
        print(f'No boundary available.')
        return
    release_notes = metadata['dataset_summary']['release_notes']
    if release_notes is None:
        release_notes = ''
    if hxgn_fix:
        release_notes += f'Hxgn fixes added'
    else:
        release_notes += f'Sidewalk lengths added'
    new_metadata = metadata.copy()
    release_notes = new_metadata['dataset_summary']['release_notes']
    if release_notes is None:
        release_notes = ''
    if hxgn_fix:
        release_notes += f'Hxgn fixes added'
    else:
        release_notes += f'Sidewalk lengths added'
    new_metadata['dataset_summary']['release_notes'] = release_notes
    new_metadata['dataset_detail']['version'] = new_version
    if not boundary['properties']:
        boundary['properties'] = {}
    boundary['properties']['name'] = ''
    boundary['properties']['id'] = mc_project_id
    boundary['properties']['tdei_service_id'] = service_id
    boundary['properties']['tdei_pg_id'] = project_group
    upload_request_response = add_mc_project_upload_request(new_metadata, boundary, tdei_access_token, mc_access_token, mc_project_id)
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




def main(tdei_access_token, mc_access_token):
    # Get the tdei dataset id from the user
    tdei_dataset_id = input('Enter the tdei dataset id: ')
    # Clean it up to avoid spaces
    tdei_dataset_id = tdei_dataset_id.strip()
    # Get the mc project id from the user
    mc_project_id = input('Enter the mc project id: ')
    # Clean it up to avoid spaces
    mc_project_id = mc_project_id.strip()
    update_dataset_with_mc(tdei_dataset_id, mc_project_id, tdei_access_token, mc_access_token,hxgn_fix=False)
    print('Check upload status in MC')
    print(f'https://yellow-coast-0f3d5b11e.5.azurestaticapps.net/project/{mc_project_id}')
    # Ask to do again
    again = input('Do you want to update another dataset? (y/n): ')
    if again.lower() == 'y':
        main(tdei_access_token, mc_access_token)
    else:
        print('Thank you for using the script')


def parse_csv(file_path:str):
    parsed_rows = []
    with open(file_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            tdei_dataset_id = row[0]
            mc_project_id = row[1]
            # update_dataset_with_mc(tdei_dataset_id, mc_project_id)
            parsed_rows.append((tdei_dataset_id, mc_project_id))
    return parsed_rows    


if __name__ == '__main__':
    tdei_access_token = login_to_tdei_system()
    mc_access_token = login_to_mc_system()
    # main(tdei_access_token, mc_access_token)
    parsed_rows = parse_csv('input.csv')
    for row in tqdm(parsed_rows, desc='Updating datasets'):
        tdei_dataset_id = row[1].strip()
        mc_project_id = row[0].strip()
        print(f'Updating dataset {tdei_dataset_id} with project id {mc_project_id}')
        update_dataset_with_mc(tdei_dataset_id, mc_project_id, tdei_access_token, mc_access_token,hxgn_fix=True)
        time.sleep(2)
        

