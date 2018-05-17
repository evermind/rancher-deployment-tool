# rancher-deployment-tool

This wrapper for the rancher cli allows to store environment specific stack configurations in simple yaml files and deploy it automatically.

## features

* check that current credentials point to the correct rancher url and environment
* define a list of stacks to deploy plus dynamic variables per stack
* verify that all variables used in docker-compose.yml are defined

## usage

```
deploy_rancher.py my-environment.yml
```

Where ```my-environment.yml``` is the configuration file with the following syntax:

```yaml
rancher-url: https://rancher-server.mycompany.com
environment: my-prod-env
stacks:
  - name: app-stack
    compose: ../stacks/app
    vars:
      APP_DOMAIN: app.mycompany.com
      APP_MODE: prod
```

* ```rancher-url``` The URL of the destination rancher server (used to verify that the credentials are correct)
* ```environment``` The destination environment (used to verify that the credentials are correct)
* ```stacks``` A list of stacks to deploy
* ```stacks/name``` The name of the stack
* ```stacks/compose``` A path to a directory where a docker-compose.yml and optionally a rancher-compose.yml are located
* ```stacks/vars``` An optional dictionary of vars that are used to substutude $VAR or ${VAR} placeholders in docker-compose.yml as well as .Values.VAR in conditionals


## planned features

* Command line option to limit deployment to certain stacks and/or services
* Command line option to force deployment, even if there are no changes
* Automatically download compose files from GIT or HTTP(S)
* (maybe) Command line option to force deployment of services if there's a new docker image version under the same tag
* Per-service batch size in config file
