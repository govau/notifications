# Notify admin

Notify admin application.

## Features of this application

- Register and manage users
- Create and manage services
- Send batch emails and SMS by uploading a CSV
- Show history of notifications

## First-time setup

Languages and tools needed:

- Python 3.6+
- [Node](https://nodejs.org/) 10.x
- [yarn](https://yarnpkg.com/en/)

The app runs within a virtual environment. We use pipenv for easier environment
management

```shell
    brew install pipenv rust openssl node@14
```

Install dependencies and build the frontend assets:

```shell 
    export PATH="/usr/local/opt/node@14/bin:$PATH"
    # https://github.com/pyca/cryptography/issues/5773#issuecomment-781576003
    env LDFLAGS="-L$(brew --prefix openssl@1.1)/lib" CFLAGS="-I$(brew --prefix openssl@1.1)/include" \
      make install
    make build-frontend
```

## Rebuilding the frontend assets

If you want the front end assets to re-compile on changes, leave this running
in a separate terminal from the app

```shell
    make run-gulp
```

## Create a local `.env` by copying .env.sample

copy the `.env.sample` file to a new file called `.env`. Pipenv will load this
when it runs commands.

## Running the application

```shell
    make run
```

Then visit [localhost:6012](http://localhost:6012)
