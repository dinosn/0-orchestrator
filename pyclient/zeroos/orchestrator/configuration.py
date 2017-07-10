def get_configuration_and_service(ays_repo):
    services = ays_repo.servicesFind(actor='configuration')
    if len(services) > 1:
        raise RuntimeError('Multiple configuration services found')

    service = services[0] if services else None
    configuration = service.model.data.to_dict()['configurations'] if service else []

    return {conf['key']: conf['value'] for conf in configuration}, service


def get_configuration(ays_repo):
    configs, _ = get_configuration_and_service(ays_repo)
    return configs


def refresh_jwt_token(token):
    import requests
    import time
    headers = {'Authorization': 'bearer %s' % token}
    params = {'validity': '3600'}
    resp = requests.get('https://itsyou.online/v1/oauth/jwt/refresh', headers=headers, params=params)
    resp.raise_for_status()
    return resp.content.decode()


def get_jwt_token(ays_repo):
    import jose
    import jose.jwt
    import requests
    import time
    configs, service = get_configuration_and_service(ays_repo)
    jwt_token = configs.get('jwt-token', '')
    jwt_key = configs.get('jwt-key')
    if not jwt_token:
        return jwt_token

    try:
        token = jose.jwt.decode(jwt_token, jwt_key)
        if token['exp'] < time.time() - 240:
            jwt_token = refresh_jwt_token(jwt_token)

        if token['exp'] > time.time() + 3600:
            raise RuntimeError('Invalid jwt-token expiration time is too long should be less than 3600 sec')

    except jose.exceptions.ExpiredSignatureError:
        jwt_token = refresh_jwt_token(jwt_token)
    except Exception:
        raise RuntimeError('Invalid jwt-token and jwt-key combination')

    for config in service.model.data.configurations:
        if config.key == 'jwt-token':
            config.value = jwt_token
            break

    service.saveAll()
    return jwt_token


def get_jwt_token_from_job(job):
    if 'token' in job.context:
        return job.context['token']

    return get_jwt_token(job.service.aysrepo)
