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
    versions = Path(settings['output'])
    headers = {'X-Api-Token': settings['api-token']}

    # load project settings
    with open('project.yml', 'r') as fp:
        project = YAML(typ='safe').load(fp)
    project_id = int(project['id'])

    # load instance settings
    with open('minecraftinstance.json', 'r') as fp:
        instance = json.load(fp)

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
        'author': project['authors'],
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
    special = {'.gitignore', 'modlist.yml', 'modlist.html', 'minecraftinstance.json', 'project.yml'}

    # prepare ZIP outputs
    if not versions.exists():
        versions.mkdir()
    client_zip = versions / (slugify(client_pack_name) + '.zip')
    server_zip = versions / (slugify(server_pack_name) + '.zip')

    # start building mod pack
    with TemporaryDirectory() as temp:
        build = Path(temp)

        # write manifest file
        with open(build / 'manifest.json', 'w') as fp:
            json.dump(manifest, fp)

        # write changelog file
        copy('modlist.html', build / 'modlist.html')

        # write modlist file
        with open(build / 'changelog.txt', 'w') as fp:
            fp.write(changelog)

        # copy files manged by Git
        process = list(repo.head.commit.tree)
        while process:
            item = process.pop()

            if item.type == 'tree':
                process += list(item)

            elif item.type == 'blob' and item.name not in special:
                destination = build / 'overrides' / item.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with open(destination, 'wb') as fp:
                    copyfileobj(item.data_stream, fp)

        # create client ZIP from the temp folder
        with ZipFile(client_zip, 'w') as fp:
            for file in build.glob('**/*'):
                fp.write(file, file.relative_to(build))

        # start building server in override folder
        build = build / 'overrides'

        # copy mods to server folder
        if not (build / 'mods').exists():
            (build / 'mods').mkdir()
        for file in managed_mods:
            copy(Path('mods') / file, build / 'mods' / file)

        # download Forge installer JAR
        forge_version = instance['baseModLoader']['minecraftVersion'] + '-' + instance['baseModLoader']['forgeVersion']
        with open(build / f'forge-{forge_version}-installer.jar', 'wb') as fp:
            fp.write(requests.get(
                f'https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_version}/forge-{forge_version}-installer.jar'
            ).content)

        # write server install scripts
        with open(build / 'install.sh', 'w', newline='\n') as fp:
            fp.write('#!/bin/sh' + '\n')
            fp.write(f'java -jar "forge-{forge_version}-installer.jar" --installServer' + '\n')
        with open(build / 'install.bat', 'w', newline='\r\n') as fp:
            fp.write('@ECHO OFF' + '\r\n')
            fp.write(f'java -jar "forge-{forge_version}-installer.jar" --installServer' + '\r\n')

        # create server ZIP from the override folder
        with ZipFile(server_zip, 'w') as fp:
            for file in build.glob('**/*'):
                fp.write(file, file.relative_to(build))

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
        f'https://www.curseforge.com/project/{project_id}/files/{upload_id}/edit'
    )

    # upload server pack to CurseForge
    resp = requests.post(
        url=f'https://minecraft.curseforge.com/api/projects/{project_id}/upload-file',
        headers=headers,
        data={'metadata': json.dumps({
            'changelog': changelog,
            'displayName': server_pack_name,
            'parentFileID': upload_id,
            'releaseType': 'beta',
        })},
        files={'file': open(server_zip, 'rb')},
    )

    # show upload results
    if not resp.ok:
        print(resp.text)
        exit(1)
    upload_id = resp.json()['id']
    webbrowser.open(
        f'https://www.curseforge.com/project/{project_id}/files/{upload_id}/edit'
    )

    # copy server ZIP to deploy location when set
    if 'latest' in settings:
        copy(server_zip, settings['latest'])

    # tag HEAD with deployed version
    tag = repo.create_tag(version)
    repo.remotes.origin.push(tag)
