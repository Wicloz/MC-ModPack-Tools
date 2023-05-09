from ruamel.yaml import YAML
import json
from pathlib import Path
import webbrowser
from jinja2 import Template
import re
from urllib.parse import quote
import sass
from bs4 import BeautifulSoup

CACHE = Path(__file__).parent / 'resources' / 'cursecache.json'
HTML = Path(__file__).parent / 'resources' / 'page.html'
SCSS = Path(__file__).parent / 'resources' / 'page.scss'

if __name__ == '__main__':
    with open('project.yml', 'r') as fp:
        project = YAML(typ='safe').load(fp)

    with open('modlist.yml', 'r') as fp:
        definitions = YAML(typ='safe').load(fp)
        if not definitions:
            definitions = []

    with open('minecraftinstance.json', 'r') as fp:
        instance = json.load(fp)

    dependencies = set()
    files = {}
    for category in definitions:
        for pid in category['addons']:
            for addon in instance['installedAddons']:
                if addon['addonID'] == pid:
                    files[pid] = addon['installedFile']['fileNameOnDisk']
                    dependencies.update(item['addonId'] for item in addon['installedFile']['dependencies'])
                    break
            else:
                files[pid] = ''

    current = set(addon for category in definitions for addon in category['addons'])
    target = set(addon['addonID'] for addon in instance['installedAddons'])

    print('Addons missing from YML:')
    for pid in target - current:
        print('> https://minecraft.curseforge.com/projects/' + str(pid))
    print()

    if CACHE.exists():
        with open(CACHE, 'r') as fp:
            cache = {int(k): v for k, v in json.load(fp).items()}
    else:
        cache = {}

    for category in definitions:
        for pid in category['addons']:
            if pid not in cache:
                webbrowser.open('https://minecraft.curseforge.com/projects/' + str(pid))
                name = input('Paste addon name: ')
                thumbnail = input('Paste link to thumbnail: ')
                cache[pid] = {'name': name, 'thumbnail': thumbnail}
                with open(CACHE, 'w') as fp:
                    json.dump(cache, fp)
                print()

    page = []
    rows = max(category['row'] for category in definitions) + 1

    for i in range(rows):
        row = []

        for category in definitions:
            if category['row'] == i:
                row.append({
                    'header': category['category'],
                    'addons': [{
                        'pid': pid,
                        'name': re.sub(r'(^|\s)[^\s]+\.[^\s]+(\s|$)', ' ',
                                       re.sub(r'\(.*?\)', '', cache[pid]['name'])).strip(),
                        'thumbnail': cache[pid]['thumbnail'],
                        'missing': files[pid] == '',
                        'disabled': files[pid].endswith('.disabled'),
                        'obsolete': category['category'] == 'Libraries' and pid not in dependencies,
                        'file': files[pid],
                    } for pid in category['addons']],
                })

        page.append(row)

    stylesheet = sass.compile(filename=str(SCSS), output_style='compressed')
    with open(HTML, 'r') as fp:
        tm = Template(fp.read())

    render = tm.render(page=page, title=project['name'], stylesheet=stylesheet)
    cleaned = BeautifulSoup(render, 'lxml').prettify()
    with open('modlist.html', 'w') as fp:
        fp.write(cleaned)

    print('Generated mod list HTML at:')
    print('file:///' + quote(str(Path().resolve() / 'modlist.html').replace('\\', '/'), ':/'))
