# Notify API

## Setting Up

### Pipenv

Install pipenv according to your platform. it can be installed through
homebrew, apt, or most easily-- pip.

```shell
    pip3 install --user pipenv
```

### `.env`

copy .env.sample to a file called `.env` and fill in the missing values with the
help of a colleague. Pipenv will read from this file in development

NOTES:

- If you want to see delivery status updated locally or are testing provider webhooks, run [ngrok](https://ngrok.com) and set `API_HOST_NAME` to be the output of `pipenv run python scripts/export-ngrok.py`
- Replace the placeholder key and prefix values as appropriate
- The `SECRET_KEY` and `DANGEROUS_SALT` should match those in the `admin` app.
- The unique prefix for the queue names prevents clashing with others' queues in shared amazon environment and enables filtering by queue name in the SQS interface.

### Postgres

Install postgres. this can be done easily through homebrew

```shell
    brew install postgres
    brew services start postgresql
```

### Redis

Install redis. this can be done easily through homebrew

```shell
    brew install redis
    brew services start redis
```

Then create a working database with the command `createdb notification_api`.

## To run the application

Then, run `make install` to install dependencies, set up your environment and
initialise the database.
```
    export PATH="/usr/local/opt/node@14/bin:$PATH"
    # https://github.com/pyca/cryptography/issues/5773#issuecomment-781576003
    env LDFLAGS="-L$(brew --prefix openssl@1.1)/lib" CFLAGS="-I$(brew --prefix openssl@1.1)/include" \
      make install
```

You can run `make setup-db` whenever you need to update your database in response
to migrations.

You need to run the api application and a local celery instance.

```shell
    make run
```

```shell
    make run-celery-worker
```

## To test the application

First, run `make install-dev` to get an environment ready for testing.

Then issue the following command to run code analysis using flake8 and our
entire test suite:

```shell
    make test
```

If you are having trouble getting all tests to pass, you may need to generate `app/version.py`:

```shell
    make version-file
```

And then edit it to look like this:

```shell
    __commit_sha__ = "?"
    __time__ = "2020-05-14:15:23:24"
    __build_job_number__ = "?"
    __build_job_url__ = "?"
```

## Using docker for your database

If you prefer using docker to isolate your database, you can
specify its connection string in your `.env` file by using the variable

```
SQLALCHEMY_DATABASE_URI="postgresql://postgres@localhost:5420/notification_api"
```

Similarly, if you prefer to use postgres for testing, you can specify that
by setting the following environment variable

```
SQLALCHEMY_TEST_DATABASE_URI="postgresql://postgres@localhost:5420/test_notification_api"
```

and then running the docker container and tests

```
    make create-docker-test-db
    make test
```

## To run one off tasks

Tasks are run through the `flask` command - run `pipenv run flask --help` for more information. There are two sections we need to
care about: `pipenv run flask db` contains alembic migration commands, and `pipenv run flask command` contains all of our custom commands.

All commands and command options have a --help command if you need more information.
