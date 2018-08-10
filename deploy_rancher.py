#!/usr/bin/env python

import logging as log
import argparse
import yaml
import re
from sys import exit
from os import path,pathsep,environ,remove as delete_file
import json
import subprocess
import tempfile

delete_after_run=[]

def none_object():
	pass

def get_as_file(basefile,location,filename):
	if (location.startswith('http://') or location.startswith('https://')):
		import requests
		if not location.endswith('/'):
			location+='/'
		location+=filename;
		r = requests.get(location)
		if r.status_code<200 or r.status_code>299:
			return (None,location)
		tmp=tempfile.NamedTemporaryFile(suffix=filename,delete=False)
		delete_after_run.append(tmp.name)
		tmp.write(r.text.encode())
		return (tmp.name,location)

	file=path.normpath(path.join(path.dirname(basefile),location,filename))
	if (path.exists(file)):
		return (file,file)
	return (None,file)


def get_config_value(file,config,name,required_type,prefix='',default=none_object):
	if name in config:
		value=config[name]
	else:
		if default is none_object:
			log.critical('missing config option in %s: %s%s',file,prefix,name)
			exit(1)
		value=default
	if value is not None and not type(value) is required_type:
		log.critical('expected type %s for config option "%s%s" but got: %s',required_type.__name__,prefix,name,type(value).__name__)
		exit(1)
	return value

def scan_vars(text):
	return set(
		re.findall('[^\$]\${(.+?)}', text) + # find $VAR
		re.findall('[^\$]\$([a-zA-Z0-9_]+)', text) + # find ${VAR}
		re.findall('{{-.*?\s+\.Values\.([a-zA-Z0-9_]+)\s+.*?}}', text) # find .Values.VAR in conditionals
		)

def parse_stacks_config(file,stacks_config):
	stacks=[]
	for config in stacks_config:
		stack_name=get_config_value(file,config,'name',str,'stack/')
		log.debug('Adding stack config "%s"',stack_name)
		compose=get_config_value(file,config,'compose',str,'stack[%s]/'%stack_name)
		vars=get_config_value(file,config,'vars',dict,'stack[%s]/'%stack_name,{})
		(docker_compose_file,docker_compose_location)=get_as_file(file,compose,'docker-compose.yml')
		if docker_compose_file:
			log.debug('  using %s',docker_compose_location)
			with open(docker_compose_file,'r') as f:
				docker_compose_raw=f.read();
			required_vars=scan_vars(docker_compose_raw)
			# remove all conditionals prior to parse the yaml
			docker_compose=yaml.safe_load(re.sub('{{-.*?}}','',docker_compose_raw))
			services=list(get_config_value(docker_compose_location,docker_compose,'services',dict).keys())
		else:
			log.critical('  File not found: %s',docker_compose_location)
			exit(1)
		(rancher_compose_file,rancher_compose_location)=get_as_file(file,compose,'rancher-compose.yml')
		if rancher_compose_file:
			log.debug('  using %s',rancher_compose_location)
		all_vars_found=True
		for var in required_vars:
			if not var in vars:
				log.critical('  Missing variable: %s',var)
				all_vars_found=False
		if not all_vars_found:
			exit(1)
		stacks.append({
			'name': stack_name,
			'vars': vars,
			'docker_compose_file': docker_compose_file,
			'rancher_compose_file': rancher_compose_file,
			'services': services
			})
	return stacks

def read_config(file):
	log.debug("Reading %s",file)
	with open(file,'r') as f:
		config=yaml.load(f)
	return {
		'rancher-url': get_config_value(file,config,'rancher-url',str),
		'environment': get_config_value(file,config,'environment',str),
		'stacks': parse_stacks_config(file,get_config_value(file,config,'stacks',list))
	}

def find_rancher_cli():
	for dir in [path.dirname(__file__)]+environ['PATH'].split(pathsep):
		cli=path.normpath(path.join(dir,'rancher'))
		if path.isfile(cli):
			return cli

	log.critical('Rancher cli not found!')
	exit(1)

def check_rancher_connection(cli,config):
	rancher_url=json.loads(subprocess.check_output([cli,'config','-p']))['url']
	if not rancher_url:
		log.critical('Unable to get rancher URL - the cli is not configured correctly')
		exit(1)
	if not rancher_url.startswith(config['rancher-url']):
		log.critical('Expected a rancher cli config that connects to %s but got: %s',config['rancher-url'],rancher_url)
		exit(1)
	envs=subprocess.check_output([cli,'env','ls','--format','{{.Environment.Name}}']).split()
	if not config['environment'] in envs:
		log.critical('Environment "%s" not found with the current cli config at %s - available environments: %s',config['environment'],config['rancher-url'],envs)
		exit(1)

	log.info("Deploying to %s on %s",config['environment'],config['rancher-url'])

def deploy_stack(args,cli,config,stack):
	if args.force:
		log.info('Deploying stack %s (force update)',stack['name'])
	else:
		log.info('Deploying stack %s',stack['name'])

	proc_env=dict(environ.copy())
	proc_env.update(stack['vars'])
	command=[
		cli,
		'--env',config['environment'],
		'up',
		'--pull',
		'--prune',
		'--upgrade',
		'--confirm-upgrade',
		'--batch-size','1',
		'--file',stack['docker_compose_file'],
		'--stack',stack['name'],
		'-d'
		]

	if stack['rancher_compose_file']:
		command+=['--rancher-file',stack['rancher_compose_file']]

	if args.force:
		command+=['--force-upgrade']

	subprocess.check_call(command,env=proc_env)


def run():
	parser = argparse.ArgumentParser(description='Rancher deployment tool',formatter_class=argparse.RawTextHelpFormatter)
	parser.add_argument('configfile',metavar='config.yml',help='The deployment config file')
	parser.add_argument('--debug','-d',action='store_true')
	parser.add_argument('--force','-f',help='Force the deployment, even if there are no changes on the stack definition',action='store_true')
#	parser.add_argument('-l',dest='limit',metavar='stack/service',nargs='*',help=('Limit the execution to the given stacks and/or services. Examples:\n'
#		'  name          - limit to the stack or service with that name\n'
#		'                  (fails if the names exists as both, stack and service)\n'
#		'  stack/service - deploy a particular service on a particular stack\n'
#		'  */service     - deploy a particular service on a all stacks where it exists\n'
#		'  stack/*       - deploy all services on a particular stack with that name\n'
#		))
	args = parser.parse_args()

	loglevel=log.DEBUG if args.debug else log.INFO
	try:
		import coloredlogs
		coloredlogs.install(level=loglevel,fmt="%(asctime)s %(levelname)8s %(message)s")
	except ModuleNotFoundError:
		log.basicConfig(format="%(asctime)s %(levelname)8s %(message)s", level=loglevel)
		log.debug("Install coloredlogs module for colored logs.")
		pass

	cli=find_rancher_cli()
	config=read_config(args.configfile)
	check_rancher_connection(cli,config)
	for stack in config['stacks']:
		deploy_stack(args,cli,config,stack)

def cleanup():
	for f in delete_after_run:
		delete_file(f)


def main():
	try:
		run()
	finally: 
		cleanup()


if __name__ == "__main__":
	main()