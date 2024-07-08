import base64
import requests
import socket
import sys
import traceback
from enum import Enum
from urllib.parse import urlsplit
from urllib.parse import urlparse
from urllib.parse import parse_qs
from mitmproxy import ctx


class HTTP(Enum):
    GET = 1
    POST = 2
    PUT = 3,
    DELETE = 4,
    PATCH = 5


class GHActionsProxy:
    def add_to_maps(self, dns):
        ip = socket.gethostbyname(dns)
        # in case of transparent proxy, host name is not available, so we build a map of ip -> dns
        self.ip_map[ip] = dns
        # to make the proxy universal let's build a map of dns -> ip when the proxy is used explicitly
        self.dns_map[dns] = ip

    def rebuild_cache(self):
        for host in ctx.options.hosts.split(','):
            self.add_to_maps(host.strip())

    def is_public_repo(self, repo):
        if repo in self.repo_map:
            return self.repo_map[repo]

        repo_path = 'repos' if '/' in repo else 'repositories'
        url = f'{ctx.options.GITHUB_API_URL}/{repo_path}/{repo}'
        response = requests.get(url, headers={'Authorization': 'Bearer %s' % ctx.options.token})
        if response.status_code == 200:
            self.repo_map[repo] = response.json()['private'] == False
            return self.repo_map[repo]
        else:
            return False

    def __init__(self):
        self.ip_map = {}
        self.dns_map = {}
        self.repo_map = {}

        self.methods_map = {
            'GET':      HTTP.GET,
            'POST':     HTTP.POST,
            'PUT':      HTTP.PUT,
            'DELETE':   HTTP.DELETE,
            'PATCH':    HTTP.PATCH
        }

        # a map of tricky permissions, that do not fall into a pattern of (GET|POST|etc) /repos/{owner}/{repo}/{what}/{id} -> {what, permission}
        map = {
            ('GET',     '/repos/{owner}/{repo}/codeowners/errors',                                  'contents',                 'read'),
            ('GET',     '/repositories/{id}/codeowners/errors',                                     'contents',                 'read'),
            ('PUT',     '/repos/{owner}/{repo}/pulls/{pull_number}/merge',                          'contents',                 'write'),
            ('PUT',     '/repositories/{id}/pulls/{pull_number}/merge',                             'contents',                 'write'),
            ('PUT',     '/repos/{owner}/{repo}/pulls/{pull_number}/update-branch',                  'contents',                 'write'),
            ('PUT',     '/repositories/{id}/pulls/{pull_number}/update-branch',                     'contents',                 'write'),
            ('POST',    '/repos/{owner}/{repo}/comments/{comment_id}/reactions',                    'contents',                 'write'),
            ('POST',    '/repositories/{id}/comments/{comment_id}/reactions',                       'contents',                 'write'),
            ('DELETE',  '/repos/{owner}/{repo}/comments/{comment_id}/reactions/{reaction_id}',      'contents',                 'write'),
            ('DELETE',  '/repositories/{id}/comments/{comment_id}/reactions/{reaction_id}',         'contents',                 'write'),
            ('GET',     '/repos/{owner}/{repo}/branches',                                           'contents',                 'read'),
            ('GET',     '/repositories/{id}/branches',                                              'contents',                 'read'),

            ('POST',    '/repos/{owner}/{repo}/merge-upstream',                                     'contents',                 'write'),
            ('POST',    '/repositories/{id}/merge-upstream',                                        'contents',                 'write'),
            ('POST',    '/repos/{owner}/{repo}/merges',                                             'contents',                 'write'),
            ('POST',    '/repositories/{id}/merges',                                                'contents',                 'write'),
            ('PATCH',   '/repos/{owner}/{repo}/comments/{comment_id}',                              'contents',                 'write'),
            ('PATCH',   '/repositories/{id}/comments/{comment_id}',                                 'contents',                 'write'),
            ('DELETE',  '/repos/{owner}/{repo}/comments/{comment_id}',                              'contents',                 'write'),
            ('DELETE',  '/repositories/{id}/comments/{comment_id}',                                 'contents',                 'write'),
            ('POST',    '/repos/{owner}/{repo}/dispatches',                                         'contents',                 'write'),
            ('POST',    '/repositories/{id}/dispatches',                                            'contents',                 'write'),

            ('POST',    '/repos/{owner}/{repo}/issues/{issue_number}/assignees',                    'issues/pull-requests',     'write'),
            ('POST',    '/repositories/{id}/issues/{issue_number}/assignees',                       'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/{issue_number}/assignees',                    'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/{issue_number}/assignees',                       'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}/comments',                     'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}/comments',                        'issues/pull-requests',     'read'),
            ('POST',    '/repos/{owner}/{repo}/issues/{issue_number}/comments',                     'issues/pull-requests',     'write'),
            ('POST',    '/repositories/{id}/issues/{issue_number}/comments',                        'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/comments',                                    'issues,pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/comments',                                       'issues,pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/issues/comments/{comment_id}',                       'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/comments/{comment_id}',                          'issues/pull-requests',     'read'),
            ('PATCH',   '/repos/{owner}/{repo}/issues/comments/{comment_id}',                       'issues/pull-requests',     'write'),
            ('PATCH',   '/repositories/{id}/issues/comments/{comment_id}',                          'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/comments/{comment_id}',                       'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/comments/{comment_id}',                          'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}/events',                       'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}/events',                          'issues/pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/issues/events',                                      'issues,pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/events',                                         'issues,pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/issues/events/{event_id}',                           'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/events/{event_id}',                              'issues/pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}/timeline',                     'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}/timeline',                        'issues/pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/assignees',                                          'issues,pull-requests',     'read'),
            ('GET',     '/repositories/{id}/assignees',                                             'issues,pull-requests',     'read'),
            ('GET',     '/repos/{owner}/{repo}/issues',                                             'issues,pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues',                                                'issues,pull-requests',     'read'),
            ('POST',    '/repos/{owner}/{repo}/issues',                                             'issues',                   'write'),
            ('POST',    '/repositories/{id}/issues',                                                'issues',                   'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}',                              'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}',                                 'issues/pull-requests',     'read'),
            ('PATCH',   '/repos/{owner}/{repo}/issues/{issue_number}',                              'issues/pull-requests',     'write'),
            ('PATCH',   '/repositories/{id}/issues/{issue_number}',                                 'issues/pull-requests',     'write'),
            ('PUT',     '/repos/{owner}/{repo}/issues/{issue_number}/lock',                         'issues/pull-requests',     'write'),
            ('PUT',     '/repositories/{id}/issues/{issue_number}/lock',                            'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/{issue_number}/lock',                         'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/{issue_number}/lock',                            'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}/labels',                       'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}/labels',                          'issues/pull-requests',     'read'),
            ('POST',    '/repos/{owner}/{repo}/issues/{issue_number}/labels',                       'issues/pull-requests',     'write'),
            ('POST',    '/repositories/{id}/issues/{issue_number}/labels',                          'issues/pull-requests',     'write'),
            ('PUT',     '/repos/{owner}/{repo}/issues/{issue_number}/labels',                       'issues/pull-requests',     'write'),
            ('PUT',     '/repositories/{id}/issues/{issue_number}/labels',                          'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/{issue_number}/labels',                       'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/{issue_number}/labels',                          'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/labels',                                             'issues',                   'read'),
            ('GET',     '/repositories/{id}/labels',                                                'issues',                   'read'),
            ('POST',    '/repos/{owner}/{repo}/labels',                                             'issues',                   'write'),
            ('POST',    '/repositories/{id}/labels',                                                'issues',                   'write'),
            ('GET',     '/repos/{owner}/{repo}/milestones/{milestone_number}/labels',               'issues',                   'read'),
            ('GET',     '/repositories/{id}/milestones/{milestone_number}/labels',                  'issues',                   'read'),
            ('GET',     '/repos/{owner}/{repo}/milestones',                                         'issues',                   'read'),
            ('GET',     '/repositories/{id}/milestones',                                            'issues',                   'read'),
            ('POST',    '/repos/{owner}/{repo}/milestones',                                         'issues',                   'write'),
            ('POST',    '/repositories/{id}/milestones',                                            'issues',                   'write'),
            ('GET',     '/repos/{owner}/{repo}/milestones/{milestone_number}',                      'issues',                   'read'),
            ('GET',     '/repositories/{id}/milestones/{milestone_number}',                         'issues',                   'read'),
            ('PATCH',   '/repos/{owner}/{repo}/milestones/{milestone_number}',                      'issues',                   'write'),
            ('PATCH',   '/repositories/{id}/milestones/{milestone_number}',                         'issues',                   'write'),
            ('DELETE',  '/repos/{owner}/{repo}/milestones/{milestone_number}',                      'issues',                   'write'),
            ('DELETE',  '/repositories/{id}/milestones/{milestone_number}',                         'issues',                   'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/{issue_number}/reactions',                    'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/{issue_number}/reactions',                       'issues/pull-requests',     'read'),
            ('POST',    '/repos/{owner}/{repo}/issues/{issue_number}/reactions',                    'issues/pull-requests',     'write'),
            ('POST',    '/repositories/{id}/issues/{issue_number}/reactions',                       'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/{issue_number}/reactions/{reaction_id}',      'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/{issue_number}/reactions/{reaction_id}',         'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions',             'issues/pull-requests',     'read'),
            ('GET',     '/repositories/{id}/issues/comments/{comment_id}/reactions',                'issues/pull-requests',     'read'),
            ('POST',    '/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions',             'issues/pull-requests',     'write'),
            ('POST',    '/repositories/{id}/issues/comments/{comment_id}/reactions',                'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions',             'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/comments/{comment_id}/reactions',                'issues/pull-requests',     'write'),
            ('DELETE',  '/repos/{owner}/{repo}/issues/{issue_number}/labels/{name}',                'issues/pull-requests',     'write'),
            ('DELETE',  '/repositories/{id}/issues/{issue_number}/labels/{name}',                   'issues/pull-requests',     'write'),
            ('GET',     '/repos/{owner}/{repo}/labels/{name}',                                      'issues',                   'read'),
            ('GET',     '/repositories/{id}/labels/{name}',                                         'issues',                   'read'),
            ('PATCH',   '/repos/{owner}/{repo}/labels/{name}',                                      'issues',                   'write'),
            ('PATCH',   '/repositories/{id}/labels/{name}',                                         'issues',                   'write'),
            ('DELETE',  '/repos/{owner}/{repo}/labels/{name}',                                      'issues',                   'write'),
            ('DELETE',  '/repositories/{id}/labels/{name}',                                         'issues',                   'write'),
        }

        try:
            # build an optimized tree for faster lookup from the map
            self.rest_api_map = {}
            for entry in map:
                path_segments = entry[1].split('/')
                node = self.rest_api_map
                for segment in path_segments[1:]:
                    # we keep {milestone_number}, {issue_number} and etc. just for readability
                    # for mapping any path segment we use special character '*'
                    if segment.startswith('{'):
                        segment = '*'

                    next_node = node.get(segment)
                    if not next_node:
                        next_node = {}
                        node[segment] = next_node

                    node = next_node

                # Every pull request is an issue, but not every issue is a pull request.
                # issues/pull-requests is a special case, we need to check if the issue is a pull request
                # The check depends on the available information from the request
                # To identify the type of check we append the id to the permission type
                type = entry[2]
                if type == 'issues/pull-requests':
                    if path_segments[1] == 'repos':
                        if path_segments[5] == '{issue_number}':
                            type += '/issue_number'
                        elif path_segments[6] == '{comment_id}':
                            type += '/comment_id'
                        elif path_segments[6] == '{event_id}':
                            type += '/event_id'
                    elif path_segments[1] == 'repositories':
                        if path_segments[4] == '{issue_number}':
                            type += '/issue_number'
                        elif path_segments[5] == '{comment_id}':
                            type += '/comment_id'
                        elif path_segments[5] == '{event_id}':
                            type += '/event_id'

                # A tree node may contain the link to the next node if the lookup path is long enough
                # or a link to the HTTP method type (GET, POST, etc.) node with the permission type
                # Here is the trick: the HTTP method type is enum/integer while next path segment is string
                # We use both types as keys in the same dictionary
                # It prevents from unlikely collision if the next path segment name was the same as the HTTP method type
                node[self.methods_map[entry[0]]] = (type, entry[3])
        except Exception as e:
            print(traceback.format_exc())
            self.log_error(traceback.format_exc())
            sys.exit(1)

    def get_permission(self, path, method, query):
        path_segments = path.split('/')

        if len(path_segments) >= 3:
            if path_segments[1] == 'repos' and not self.same_repository(path_segments[2], path_segments[3]):
                return []
        elif len(path_segments) >= 2:
            if path_segments[1] == 'repositories' and not self.same_repository(path_segments[2]):
                return []

        # First try to find the permission in the tree of special cases
        node = self.rest_api_map
        for segment in path_segments[1:]:
            next_node = node.get(segment)
            if not next_node:
                next_node = node.get('*')
                if not next_node:
                    node = next_node
                    break
            node = next_node

        # If the node was found extract the permission
        if node:
            permissions = node.get(self.methods_map[method])
            if permissions:  # If the node was found, but the HTTP method wasn't, fall through to search by path pattern
                if permissions[0].startswith('issues/pull-requests'):
                    # Every pull request is an issue, but not every issue is a pull request case. Try to find out the type.
                    id = permissions[0].split('/')[2]
                    if id == 'issue_number':
                        url = ''
                        if path_segments[1] == 'repos':
                            url = f'{ctx.options.GITHUB_API_URL}/repos/{path_segments[2]}/{path_segments[3]}/pulls/{path_segments[5]}'
                        elif path_segments[1] == 'repositories':
                            url = f'{ctx.options.GITHUB_API_URL}/repositories/{path_segments[2]}/pulls/path_segments[4]'
                        response = requests.get(
                            url, headers={'Authorization': 'Bearer %s' % ctx.options.token})
                        self.log_debug(
                            "get_permission response: %s" % response)
                        if response.status_code == 200:
                            return [('pull-requests', permissions[1])]
                        else:
                            return [('issues', permissions[1])]
                    elif id == 'comment_id':
                        url = ''
                        if path_segments[1] == 'repos':
                            url = f'{ctx.options.GITHUB_API_URL}/repos/{path_segments[2]}/{path_segments[3]}/issues/comments/{path_segments[6]}'
                        elif path_segments[1] == 'repositories':
                            url = f'{ctx.options.GITHUB_API_URL}/repositories/{path_segments[2]}/issues/comments/{path_segments[5]}'
                        response = requests.get(
                            url, headers={'Authorization': 'Bearer %s' % ctx.options.token})
                        self.log_debug(
                            "get_permission response: %s" % response)
                        if response.status_code == 200:
                            data = response.json()
                            self.log_debug("get_permission data: %s" % data)
                            if '/pull/' in data['html_url']:
                                return [('pull-requests', permissions[1])]
                            else:
                                return [('issues', permissions[1])]
                        else:
                            return [('unknown', 'unknown')]
                    elif id == 'event_id':
                        url = ''
                        if path_segments[1] == 'repos':
                            url = f'{ctx.options.GITHUB_API_URL}/repos/{path_segments[2]}/{path_segments[3]}/issues/events/{path_segments[6]}'
                        elif path_segments[1] == 'repositories':
                            url = f'{ctx.options.GITHUB_API_URL}/repositories/{path_segments[2]}/issues/events/{path_segments[5]}'
                        response = requests.get(
                            url, headers={'Authorization': 'Bearer %s' % ctx.options.token})
                        self.log_debug(
                            "get_permission response: %s" % response)
                        if response.status_code == 200:
                            data = response.json()
                            self.log_debug("get_permission data: %s" % data)
                            if '/pull/' in data['issue']['html_url']:
                                return [('pull-requests', permissions[1])]
                            else:
                                return [('issues', permissions[1])]
                        else:
                            return [('unknown', 'unknown')]
                elif 'issues,pull-requests' == permissions[0]:
                    # It is impossible to distinguish between issues and pull requests
                    # The safest bet is to return both
                    # Also, assuming the workflow runs with full permissions the request would return both issues and pull requests anyway
                    return [('issues', permissions[1]), ('pull-requests', permissions[1])]

                return [permissions]

        # Get the permission by the pattern of (GET|POST|etc) /repos/{owner}/{repo}/{what}/{id} -> {what, permission}
        if len(path_segments) >= 5:
            if path_segments[1] == 'repos' and path_segments[4] == 'actions':
                if method == 'GET' and self.is_public_repo(f'{path_segments[2]}/{path_segments[3]}'):
                    return []
                return [('actions', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'environments':
                if method == 'GET' and self.is_public_repo(f'{path_segments[2]}/{path_segments[3]}'):
                    return []
                return [('actions', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and (path_segments[4] == 'check-runs' or path_segments[4] == 'check-suites'):
                return [('checks', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and (path_segments[4] == 'releases' or path_segments[4] == 'git' or path_segments[4] == 'commits'):
                if method == 'GET' and self.is_public_repo(f'{path_segments[2]}/{path_segments[3]}'):
                    return []
                return [('contents', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'deployments':
                return [('deployments', 'read' if method == 'GET' else 'write')]
            # Issues are covered by the mapping above
            # TODO: only GraphQL API for discussions?
            elif ((path_segments[1] == 'orgs' or path_segments[1] == 'users') and path_segments[3] == 'packages') or (path_segments[1] == 'user' and path_segments[2] == 'packages'):
                return [('packages', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'pages':
                return [('pages', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'pulls':
                return [('pull-requests', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'projects' or (path_segments[1] == 'repos' and path_segments[4] == 'projects'):
                return [('repository-projects', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'code-scanning':
                return [('security-events', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and path_segments[4] == 'statuses':
                return [('statuses', 'read' if method == 'GET' else 'write')]
            elif path_segments[3] == 'info' and path_segments[4] == 'refs':
                if query['service'][0] == 'git-upload-pack':
                    if self.is_public_repo(f'{path_segments[1]}/{path_segments[2]}'):
                        return []
                    return [('contents', 'read')]
                elif query['service'][0] == 'git-receive-pack':
                    return [('contents', 'write')]

        if len(path_segments) >= 4:
            if path_segments[1] == 'repositories' and path_segments[3] == 'actions':
                if method == 'GET' and self.is_public_repo(path_segments[2]):
                    return []
                return [('actions', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'environments':
                if method == 'GET' and self.is_public_repo(path_segments[2]):
                    return []
                return [('actions', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and (path_segments[3] == 'check-runs' or path_segments[3] == 'check-suites'):
                return [('checks', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and (path_segments[3] == 'releases' or path_segments[3] == 'git' or path_segments[3] == 'commits'):
                if method == 'GET' and self.is_public_repo(path_segments[2]):
                    return []
                return [('contents', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'deployments':
                return [('deployments', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'pages':
                return [('pages', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'pulls':
                return [('pull-requests', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'projects':
                return [('repository-projects', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'code-scanning':
                return [('security-events', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repositories' and path_segments[3] == 'statuses':
                return [('statuses', 'read' if method == 'GET' else 'write')]
            elif path_segments[1] == 'repos' and method == 'GET' and len(path_segments) == 4:
                return [] # it successfully returns the repository even with permissions: {}
            elif path_segments[1] == 'projects':
                return [('repository-projects', 'read' if method == 'GET' else 'write')]
            elif path_segments[3] == 'git-upload-pack':
                if self.is_public_repo(f'{path_segments[1]}/{path_segments[2]}'):
                    return []
                return [('contents', 'read')]
            elif path_segments[3] == 'git-receive-pack':
                return [('contents', 'write')]
        elif len(path_segments) == 3:
            if (path_segments[1] == 'repositories' or path_segments[1] == 'users') and method == 'GET':
                return [] # it successfully returns even with permissions: {}
            elif path_segments[1] == 'projects':
                return [('repository-projects', 'read' if method == 'GET' else 'write')]

        return [('unknown', 'unknown')]

    def same_repository(self, id):
        return ctx.options.GITHUB_REPOSITORY_ID.upper() == id.upper()

    def same_repository(self, owner, repo):
        return ctx.options.GITHUB_REPOSITORY.upper() == f'{owner}/{repo}'.upper()

    def load(self, loader):
        loader.add_option(
            name='output',
            typespec=str,
            default='',
            help='Output file path',
        )
        loader.add_option(
            name='token',
            typespec=str,
            default='',
            help='GitHub token',
        )
        loader.add_option(
            name='debug',
            typespec=str,
            default='',
            help='Enable debug logging',
        )
        loader.add_option(
            name='ACTIONS_ID_TOKEN_REQUEST_URL',
            typespec=str,
            default='',
            help='ACTIONS_ID_TOKEN_REQUEST_URL environment variable',
        )
        loader.add_option(
            name='ACTIONS_ID_TOKEN_REQUEST_TOKEN',
            typespec=str,
            default='',
            help='ACTIONS_ID_TOKEN_REQUEST_TOKEN environment variable',
        )
        loader.add_option(
            name='GITHUB_REPOSITORY_ID',
            typespec=str,
            default='',
            help='GITHUB_REPOSITORY_ID environment variable',
        )
        loader.add_option(
            name='GITHUB_REPOSITORY',
            typespec=str,
            default='',
            help='GITHUB_REPOSITORY environment variable',
        )
        loader.add_option(
            name='hosts',
            typespec=str,
            default='',
            help='Comma delimited list of hosts to monitor',
        )
        loader.add_option(
            name='GITHUB_API_URL',
            typespec=str,
            default='',
            help='GITHUB_API_URL environment variable',
        )

    def log_debug(self, msg):
        if ctx.options.debug:
            with open('debug.log', 'a+') as f:
                f.write('%s\n' % msg)

    def log_error(self, msg):
        with open('error.log', 'a+') as f:
            f.write('%s\n' % msg)

    def configure(self, updates):
        self.log_debug('Proxy debug messages enabled')

        with open(ctx.options.output, 'a+') as f:
            pass  # create empty file

        if not bool(ctx.options.hosts):
            print('error: Hosts argument is empty')
            sys.exit(1)

        self.rebuild_cache()
        print(self.ip_map)
        self.log_debug(self.ip_map)

        if not bool(ctx.options.token):
            print('error: GitHub token is empty')
            sys.exit(1)

        if not bool(ctx.options.GITHUB_REPOSITORY_ID):
            print('error: GITHUB_REPOSITORY_ID is empty')
            sys.exit(1)

        if not bool(ctx.options.GITHUB_REPOSITORY):
            print('error: GITHUB_REPOSITORY is empty')
            sys.exit(1)

        if not bool(ctx.options.GITHUB_API_URL):
            print('error: GITHUB_API_URL is empty')
            sys.exit(1)

        self.id_token_request_url = None
        if bool(ctx.options.ACTIONS_ID_TOKEN_REQUEST_URL):
            self.id_token_request_url = urlsplit(ctx.options.ACTIONS_ID_TOKEN_REQUEST_URL)

        self.id_token_request_token = None
        if bool(ctx.options.ACTIONS_ID_TOKEN_REQUEST_TOKEN):
            self.id_token_request_token = ctx.options.ACTIONS_ID_TOKEN_REQUEST_TOKEN

    def contains_token(self, header, token):
        if header.upper().strip().startswith('BASIC '):
            return token in base64.b64decode(header[6:]).decode()

        return token in header

    def requestheaders(self, flow):
        try:
            url_parts = urlsplit(flow.request.url)
            parsed_url = urlparse(flow.request.url)
            hostname = url_parts.hostname.lower()

            host = None
            for k, v in flow.request.headers.items():
                if k.upper().strip() == 'HOST':
                    host = v
                    break

            if host:
                hostname = host.lower().strip()
            else:
                if not hostname in self.dns_map and not hostname in self.ip_map:
                    # we hit a load balancer, let's try to refresh the known ips
                    self.rebuild_cache()

                if hostname in self.ip_map or hostname in self.dns_map:
                    # if the hostname if found, let's replace the ip with the hostname for more readable logs
                    if url_parts.hostname in self.ip_map:
                        hostname = self.ip_map[url_parts.hostname]

            self.log_debug('%s %s' % (
                flow.request.method, flow.request.url.replace(url_parts.hostname, hostname)))

            # log a JSON like (no comma separators between objects and no wrapping array) list of objects, that will be post-processed later
            for k, v in flow.request.headers.items():
                if k.upper().strip().startswith('AUTHORIZATION'):
                    self.log_debug('The request contains an authorization header')
                    if self.contains_token(v, ctx.options.token):
                        if hostname in self.ip_map or hostname in self.dns_map:
                            permissions = self.get_permission(
                                url_parts.path, flow.request.method, parse_qs(parsed_url.query))
                            self.write_json(permissions, flow.request.method, hostname, url_parts.path)
                    elif self.id_token_request_token and self.contains_token(v, self.id_token_request_token):
                        if self.id_token_request_url and flow.request.method == 'GET' and hostname == self.id_token_request_url.hostname.lower() and url_parts.path.lower() == self.id_token_request_url.path.lower():
                            self.write_json([('id-token', 'write')], flow.request.method, hostname, url_parts.path)

        except Exception as e:
            print(traceback.format_exc())
            self.log_error(traceback.format_exc())

    def write_json(self, permissions, method, host, path):
        with open(ctx.options.output, 'a+') as f:
            f.write('{ ')
            f.write('"method": "%s"' % method)
            f.write(', "host": "%s"' % host)
            f.write(', "path": "%s"' % path)
            f.write(', "permissions": [')
            first = True
            for p in permissions:
                if not first:
                    f.write(', ')
                f.write('{"%s": "%s"}' % (p[0], p[1]))
                first = False

            f.write(']}\n')


addons = [GHActionsProxy()]
