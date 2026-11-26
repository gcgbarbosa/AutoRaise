# AutoRaise

## Requirements

### Database settings

You need to change three configs:

- Add the `command` to enable binlogs
- Add the `environment`: _MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASS}_
- Add `ports` to gain direct access to the database,
  unless you're running the scripts from the docker network itself.

```yml
mysql:
  command:
    - --log-bin=/var/log/mysql/mariadb-bin
    - --log-basename=mariadb
    - --binlog-format=ROW
    - --server-id=1
    - --expire-logs-days=7
  environment:
    MYSQL_DATABASE: ${DB_NAME}
    MYSQL_USER: ${DB_USER}
    MYSQL_PASSWORD: ${DB_PASS}
    MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASS}
  ports:
    - "127.0.0.1:63306:3306"
```

### A harness

In our experiments, we used <https://omp.sh/> with default settings.

### The skill

The skill is in [.omp/skills/wikibase-fast-insert](.omp/skills/wikibase-fast-insert/README.md).
If you're using other harnesses, adjust acoordingly.

## Synthesizing

For this step you need a fresh copy of Wikibase,
with the same settings you will use your production environment.

Copy `.env.example` to `.env` and fill the required values.
Then open `omp`, type `/skill:wikibase-fast-insert`
and wait for the process to end.

After the synthesis, you need to reset your copy of Wikibase fresh again for ingestion.

## Ingesting data

Using the final result to ingest data to your Wikibase instance
uses the same workflow from [WikibaseIntegrator](https://github.com/LeMyst/WikibaseIntegrator).

```python
import asyncio
from arw.db import FastWbi

fast_wbi = FastWbi()

new_item = wbi.item.new()
new_item.labels.set('en', 'New Item')
new_item_json = new_item.get_json()

asyncio.run(fast_wbi.write([new_item_json]))
```

After the bulk ingestion process,
you can disable the settings added to the database earlier.
