import json
from pathlib import Path
from tempfile import TemporaryDirectory
from git import Repo
from shutil import copyfileobj, copy
from zipfile import ZipFile
import requests
from ruamel.yaml import YAML
import webbrowser
from slugify import slugify

if __name__ == '__main__':
    # load export settings
    with open('export.yml', 'r') as fp:
        settings = YAML(typ='safe').load(fp)
    project_id = str(settings['project'])
    versions = Path(settings['output'])

    # construct API headers
    headers = {
        'X-Api-Token': settings['api-token'],
        'X-Api-Key': settings['api-key'],
    }

    # load project and instance data
    project = requests.get('https://api.curseforge.com/v1/mods/' + project_id, headers=headers).json()['data']
    with open('minecraftinstance.json', 'r') as fp:
        instance = json.load(fp)
    print(json.dumps(instance, indent=2))

    # request version and changelog from user
    version = input('Enter New Version: ')
    changelog = input('Enter Changelog: ')

    # determine names for uploads
    client_pack_name = f'Version {version} Client'
    server_pack_name = f'Version {version} Server'

    # build initial manifest
    manifest = {
        'minecraft': {
            'version': instance['gameVersion'],
            'modLoaders': [{
                'id': instance['baseModLoader']['name'],
                'primary': True,
            }],
        },
        'manifestType': 'minecraftModpack',
        'manifestVersion': 1,
        'name': project['name'],
        'version': version,
        'author': project['authors'][0]['name'],
        'files': [],
        'overrides': 'overrides',
    }

    # add managed mods to manifest
    managed_mods = []
    for addon in instance['installedAddons']:
        manifest['files'].append({
            'projectID': addon['addonID'],
            'fileID': addon['installedFile']['id'],
            'required': not addon['installedFile']['FileNameOnDisk'].endswith('.disabled'),
        })
        managed_mods.append(addon['installedFile']['FileNameOnDisk'])

    # prepare repository objects
    repo = Repo()
    special = {'.gitignore', 'modlist.yml', 'modlist.html'}

    # prepare ZIP outputs
    if not versions.exists():
        versions.mkdir()
    client_zip = versions / (slugify(client_pack_name) + '.zip')
    server_zip = versions / (slugify(server_pack_name) + '.zip')

    # start building mod pack
    with TemporaryDirectory() as temp:
        temp = Path(temp)

        # write manifest file
        with open(temp / 'manifest.json', 'w') as fp:
            json.dump(manifest, fp)

        # write changelog file
        with open(temp / 'modlist.html', 'w') as fp_w:
            with open('modlist.html', 'r') as fp_r:
                copyfileobj(fp_r, fp_w)

        # write modlist file
        with open(temp / 'changelog.txt', 'w') as fp:
            fp.write(changelog)

        # copy files manged by Git
        process = list(repo.head.commit.tree)
        while process:
            item = process.pop()

            if item.type == 'tree':
                process += list(item)

            elif item.type == 'blob' and item.name not in special:
                target = temp / 'overrides' / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, 'wb') as fp:
                    copyfileobj(item.data_stream, fp)

        # create client ZIP from the temp folder
        with ZipFile(client_zip, 'w') as fp:
            for file in temp.glob('**/*'):
                fp.write(file, file.relative_to(temp))

        # copy mods to server folder
        if not (temp / 'overrides' / 'mods').exists():
            (temp / 'overrides' / 'mods').mkdir()
        for file in managed_mods:
            copy(Path('mods') / file, temp / 'overrides' / 'mods' / file)

        # download Forge installer JAR
        forge_version = instance['baseModLoader']['minecraftVersion'] + '-' + instance['baseModLoader']['forgeVersion']
        with open(temp / 'overrides' / f'forge-{forge_version}-installer.jar', 'wb') as fp:
            fp.write(requests.get(
                f'https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_version}/forge-{forge_version}-installer.jar'
            ).content)

        # write server install scripts
        with open(temp / 'overrides' / 'install.sh', 'w', newline='\n') as fp:
            fp.write('#!/bin/sh' + '\n')
            fp.write(f'java -jar "forge-{forge_version}-installer.jar" --installServer' + '\n')
        with open(temp / 'overrides' / 'install.bat', 'w', newline='\r\n') as fp:
            fp.write('@ECHO OFF' + '\r\n')
            fp.write(f'java -jar "forge-{forge_version}-installer.jar" --installServer' + '\r\n')

        # create server ZIP from the override folder
        with ZipFile(server_zip, 'w') as fp:
            for file in (temp / 'overrides').glob('**/*'):
                fp.write(file, file.relative_to(temp / 'overrides'))

    # determine game ids for version
    game_ids = []
    for game in requests.get('https://minecraft.curseforge.com/api/game/versions', headers=headers).json():
        if game['name'] == instance['gameVersion'] and game['gameVersionTypeID'] == 73407:
            game_ids.append(game['id'])

    # allow user to check results
    print()
    print(f'Please check ZIP files at "{versions.resolve()}"')
    input('Press Enter to Confirm Upload')

    # upload client pack to CurseForge
    resp = requests.post(
        url=f'https://minecraft.curseforge.com/api/projects/{project_id}/upload-file',
        headers=headers,
        data={'metadata': json.dumps({
            'changelog': changelog,
            'displayName': client_pack_name,
            'gameVersions': game_ids,
            'releaseType': 'beta',
        })},
        files={'file': open(client_zip, 'rb')},
    )

    # show upload results
    if not resp.ok:
        print(resp.text)
        exit(1)
    upload_id = resp.json()['id']
    webbrowser.open(
        'https://www.curseforge.com/minecraft/modpacks/' + project['slug'] + '/files/' + str(upload_id)
    )

    # upload server pack to CurseForge
    resp = requests.post(
        url=f'https://minecraft.curseforge.com/api/projects/{project_id}/upload-file',
        headers=headers,
        data={'metadata': json.dumps({
            'changelog': changelog,
            'displayName': server_pack_name,
            'parentFileID': upload_id,
            'additionalFileInfo': 'serverPack',
            'releaseType': 'beta',
        })},
        files={'file': open(server_zip, 'rb')},
    )
    if not resp.ok:
        print(resp.text)
        exit(1)
