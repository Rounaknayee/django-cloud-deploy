# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate source files of a django app ready to be deployed to GKE."""

import os
import sys
from typing import Any, Dict, List, Optional

import django
from django.core.management import utils
from django.utils import version
import jinja2


class _FileGenerator(object):
    """An abstract class to generate files using templates."""

    def _get_template_folder_path(self) -> str:
        dirname, _ = os.path.split(os.path.abspath(__file__))
        return os.path.join(dirname, 'templates')

    @staticmethod
    def exist(project_dir: str, project_name: str) -> bool:
        """Returns whether the directory contains files to be generated."""
        raise NotImplementedError()


class _Jinja2FileGenerator(_FileGenerator):
    """A class to generate files with Jinja2."""

    REWRITE_TEMPLATE_SUFFIXES = (
        # Allow shipping invalid .py files without byte-compilation.
        ('.py-tpl', '.py'),
        ('.html-tpl', '.html'),
        ('.css-tpl', '.css'),)

    def __init__(self):
        self._template_env = jinja2.Environment()

    def _render_file(self,
                     template_path: str,
                     output_path: str,
                     options: Optional[Dict[str, Any]] = None):
        """Render a single file with template.

        Args:
            template_path: Absolute path of the template to render a file.
            output_path: Absolute path of the output file.
            options: Options used to render the file.
        """
        if not options:
            options = {}
        with open(template_path) as template_file:
            content = template_file.read()
        template = self._template_env.from_string(content)
        content = template.render(options)
        with open(output_path, 'w') as new_file:
            new_file.write(content)

    def _render_directory(self,
                          template_dir: str,
                          output_dir: str,
                          template_replacement: Optional[Dict[str, str]] = None,
                          options: Optional[Dict[str, Any]] = None):
        """Render all templates in a directory.

        Args:
            template_dir: Absolute path of the folder containing all template
                files.
            output_dir: Absolute path of the output folder.
            template_replacement: Strings in template file names to get replaced
                in the output.
            options: Options used to render the directory.
        """

        prefix_length = len(template_dir) + 1

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        for root, _, files in os.walk(template_dir):
            path_rest = root[prefix_length:]
            if template_replacement:
                for before, after in template_replacement.items():
                    path_rest = path_rest.replace(before, after)
            relative_dir = path_rest
            if relative_dir:
                target_dir = os.path.join(output_dir, relative_dir)
                if not os.path.exists(target_dir):
                    os.mkdir(target_dir)

            for file_name in files:
                old_path = os.path.join(root, file_name)
                new_path = os.path.join(output_dir, relative_dir, file_name)
                for old_suffix, new_suffix in self.REWRITE_TEMPLATE_SUFFIXES:
                    if new_path.endswith(old_suffix):
                        new_path = new_path[:-len(old_suffix)] + new_suffix
                        break  # Only rewrite once
                self._render_file(old_path, new_path, options)


class _DjangoFileGenerator(_Jinja2FileGenerator):
    """Generate Django project files and app files."""

    APP_TEMPLATE_FOLDER = 'app_template'
    ADMIN_TEMPLATE_FOLDER = 'admin_template'
    PROJECT_TEMPLATE_FOLDER = 'project_template'
    TEMPLATES_TEMPLATE_FOLDER = 'templates_template'
    STATIC_TEMPLATE_FOLDER = 'static_template'

    @staticmethod
    def exist(project_dir: str, project_name: str) -> bool:
        """Returns whether the directory contains Django files."""

        # TODO: Be able to handle more complex cases
        files_list = os.listdir(project_dir)
        if 'manage.py' not in files_list or project_name not in files_list:
            return False
        files_list = os.listdir(os.path.join(project_dir, project_name))
        if 'urls.py' not in files_list:
            return False
        return True

    def generate_project_files(self, project_name: str, destination: str):
        """Create a django project using our template.

        Args:
            project_name: Name of the project to be created.
            destination: The destination path to hold files of the project.
        """
        options = {
            'project_name': project_name,
            'docs_version': version.get_docs_version(),
        }
        filename_template_replacement = {
            'project_name': project_name,
        }
        self._generate_files(self.PROJECT_TEMPLATE_FOLDER, destination,
                             filename_template_replacement, options)

    def generate_app_files(self, app_name: str, destination: str):
        """Create a django app using our template.

        Args:
            app_name: Name of the app to be created.
            destination: Destination path to hold files of the app.
        """
        app_destination = os.path.join(destination, app_name)
        camel_case_value = ''.join(x for x in app_name.title() if x != '_')
        options = {
            'app_name': app_name,
            'camel_case_app_name': camel_case_value
        }
        self._generate_files(self.APP_TEMPLATE_FOLDER,
                             app_destination, options=options)

    def generate_admin_files(self,
                             project_id: str,
                             project_name: str,
                             destination: str):
        """Create the django admin using our template.

        Args:
            project_id: The GCP project id.
            project_name: Name of the project to be created.
            destination: Destination path to hold files.
        """
        options = {
            'project_id': project_id,
            'project_name': project_name
        }
        admin_destination = os.path.join(destination, 'cloud_admin')
        self._generate_files(self.ADMIN_TEMPLATE_FOLDER,
                             admin_destination,
                             options=options)

    def generate_templates_files(self, destination: str):
        """Create the django templates using our template.

        Args:
            destination: Destination path to hold files.
        """
        templates_destination = os.path.join(destination, 'templates')
        self._generate_files(self.TEMPLATES_TEMPLATE_FOLDER,
                             templates_destination)

    def generate_static_files(self, destination: str):
        """Create our custom static files for the django app.

        Args:
            destination: Destination path to hold files.
        """
        static_destination = os.path.join(destination, 'staticfiles')
        self._generate_files(self.STATIC_TEMPLATE_FOLDER,
                             static_destination)

    def _generate_files(self, folder_name: str, destination: str,
                        filename_template_replacement=None, options=None):
        """Consolidates duplicate code that calls render_directory.

        Args:
            folder_name: Name of the folder that holds the templates
            destination: The destination path to hold files of the app.
            filename_template_replacement: Strings in template file names to
                get replaced in the output.
            options: Options used to render the directory.
        """
        if options is None:
            options = {}
        destination = os.path.abspath(os.path.expanduser(destination))
        templates_dir = os.path.join(self._get_template_folder_path(),
                                     folder_name)
        self._render_directory(templates_dir, destination,
                               filename_template_replacement, options)


class _SettingsFileGenerator(_Jinja2FileGenerator):
    """Generate Django settings file."""

    _SETTINGS_TEMPLATE_DIRECTORY = 'settings_template'

    @staticmethod
    def exist(project_dir: str, project_name: str) -> bool:
        """Returns whether the directory contains Django fils."""

        # TODO: Be able to handle more complex cases
        files_list = os.listdir(project_dir)
        return 'settings.py' in files_list

    def generate_new(self,
                     project_id: str,
                     project_name: str,
                     destination: str,
                     cloud_sql_connection: str,
                     database_name: Optional[str] = None,
                     cloud_storage_bucket_name: Optional[str] = None):
        """Create Django settings file using our template.

        Args:
            project_id: GCP project id.
            project_name: Name of the project to be created.
            destination: The destination path to hold files of the project.
            database_name: Name of your cloud database.
            cloud_storage_bucket_name: Google Cloud Storage bucket name to
                serve static content.
            cloud_sql_connection: Connection string to allow the django app
                to connect to the cloud sql proxy.
        """
        database_name = database_name or project_name + '-db'
        destination = os.path.join(
            os.path.abspath(os.path.expanduser(destination)), project_name)
        cloud_storage_bucket_name = cloud_storage_bucket_name or project_id
        settings_templates_dir = os.path.join(self._get_template_folder_path(),
                                              self._SETTINGS_TEMPLATE_DIRECTORY)
        options = {
            'project_id': project_id,
            'project_name': project_name,
            'docs_version': version.get_docs_version(),
            'secret_key': utils.get_random_secret_key(),
            'database_name': database_name,
            'bucket_name': cloud_storage_bucket_name,
            'cloud_sql_connection': cloud_sql_connection
        }
        self._render_directory(settings_templates_dir, destination,
                               options=options)

    def generate_from_existing(self,
                               project_id: str,
                               project_name: str,
                               destination: str,
                               database_name: Optional[str] = None,
                               cloud_storage_bucket_name: Optional[str] = None):
        """Create Django settings file from an existing settings file.

        We made several assumptions:
            1. The existing settings file is in
               <project_dir>/<project_name>/settings.py
            2. There is only one settings file.

        This is achieved by rename the existing settings file to
        "base_settings.py", then create "local_settings.py" and
        "remote_settings.py" from our templates. "local_settings.py" and
        "remote_settings.py" inherits "base_settings.py", so the existing
        settings file still have effects, and we only override what we need to.

        Args:
            project_id: GCP project id.
            project_name: Name of the project to be created.
            destination: The destination path to hold files of the project.
            database_name: Name of your cloud database.
            cloud_storage_bucket_name: Google Cloud Storage bucket name to
                serve static content.
        """
        database_name = database_name or project_name + '-db'
        cloud_storage_bucket_name = cloud_storage_bucket_name or project_id

        settings_templates_dir = os.path.join(self._get_template_folder_path(),
                                              self._SETTINGS_TEMPLATE_DIRECTORY)
        local_settings_tpl_path = os.path.join(settings_templates_dir,
                                               'local_settings.py-tpl')
        remote_settings_tpl_path = os.path.join(settings_templates_dir,
                                                'remote_settings.py-tpl')
        project_dir = os.path.join(destination, project_name)

        # TODO: Make it smart enough to find settings file instead of hard
        # coding settings file path.
        settings_file_path = os.path.join(project_dir, 'settings.py')
        base_settings_path = os.path.join(project_dir, 'base_settings.py')
        local_settings_path = os.path.join(project_dir, 'local_settings.py')
        remote_settings_path = os.path.join(project_dir, 'remote_settings.py')
        os.rename(settings_file_path, base_settings_path)
        options = {
            'project_id': project_id,
            'project_name': project_name,
            'docs_version': version.get_docs_version(),
            'secret_key': utils.get_random_secret_key(),
            'database_name': database_name,
            'bucket_name': cloud_storage_bucket_name
        }
        self._render_file(local_settings_tpl_path, local_settings_path, options)
        self._render_file(remote_settings_tpl_path, remote_settings_path,
                          options)


class _DockerfileGenerator(_Jinja2FileGenerator):
    """Generate Dockerfile to build image for the Django project."""

    def generate(self, project_name: str, destination: str):
        """Generate Dockerfile and .dockerignore.

        Args:
            project_name: The name of your Django project.
            destination: The destination directory path to put Dockerfile.
        """
        file_names = ('Dockerfile', '.dockerignore')
        options = {'project_name': project_name}
        for file_name in file_names:
            template_path = os.path.join(self._get_template_folder_path(),
                                         file_name)
            output_path = os.path.join(destination, file_name)
            self._render_file(template_path, output_path, options)

class _AppEngineFileGenerator(_Jinja2FileGenerator):
    """Generate App Engine Files for the Django project."""

    # TODO: remove database_password
    def generate(self, project_name: str, destination: str,
                 database_password: str):
        """Generate Dockerfile and .dockerignore.

        Args:
            project_name: The name of your Django project.
            destination: The destination directory path to put Dockerfile.
            database_password: Plaintext password of the database.
        """
        self._generate_ignore(destination)
        self._generate_yaml(destination, project_name, database_password)

    def _generate_ignore(self, destination: str):
        file_name = '.gcloudignore'
        template_path = os.path.join(self._get_template_folder_path(),
                                     file_name)
        output_path = os.path.join(destination, file_name)
        self._render_file(template_path, output_path)

    def _generate_yaml(self, destination: str,
                       project_name: str,
                       database_password: str):
        file_name = 'app.yaml'
        options = {
            'project_name': project_name,
            'db_password': database_password
        }
        template_path = os.path.join(self._get_template_folder_path(),
                                     file_name)
        output_path = os.path.join(destination, file_name)
        self._render_file(template_path, output_path, options)


class _DependencyFileGenerator(_Jinja2FileGenerator):
    """Generate dependencis needed by Django project."""

    def generate(self, destination: str):
        """Generate requirements.txt.

        Dependencies are hardcoded.

        Args:
            destination: The destination directory path to put requirements.txt.
        """

        # TODO: Find a way to determine the correct package version
        # instead of hardcoding everything.
        file_name = 'requirements.txt'
        template_path = os.path.join(self._get_template_folder_path(),
                                     file_name)
        output_path = os.path.join(destination, file_name)
        self._render_file(template_path, output_path)


class _YAMLFileGenerator(_Jinja2FileGenerator):
    """Generate YAML file which defines Kubernete deployment and service."""

    def generate(self,
                 destination: str,
                 project_name: str,
                 project_id: str,
                 instance_name: Optional[str] = None,
                 region: Optional[str] = 'us-west1',
                 image_tag: Optional[str] = None,
                 cloudsql_secrets: Optional[List[str]] = None,
                 django_secrets: Optional[List[str]] = None):
        """Generate YAML file which defines Kubernete deployment and service.

        Args:
            destination: The destination directory path to put the yaml
                file.
            project_name: Name of your Django project.
            project_id: Your GCP project id. This can be got from your GCP
                console.
            instance_name: The name of cloud sql instance for
                database or the Django project. The default value for
                instance_name should be "{project_name}-instance".
            region: Where to host the Django project.
            image_tag: A customized docker image tag used in integration tests.
            cloudsql_secrets: A list of secrets needed by cloud sql proxy
                container.
            django_secrets: A list of secrets needed by Django app
                container.
        """
        file_name = 'project_name.yaml'
        image_tag = image_tag or '/'.join(['gcr.io', project_id, project_name])
        instance_name = instance_name or project_name + '-instance'

        # This string is used by cloud sql proxy and specifies how to connect to
        # your cloud sql instance.
        cloud_sql_connection_string = '{}:{}:{}'.format(project_id, region,
                                                        instance_name)
        cloudsql_secrets = cloudsql_secrets or ['cloudsql-oauth-credentials']
        django_secrets = django_secrets or []

        options = {
            'project_name': project_name,
            'project_id': project_id,
            'cloud_sql_connection_string': cloud_sql_connection_string,
            'image_tag': image_tag,
            'cloudsql_secrets': cloudsql_secrets,
            'django_secrets': django_secrets
        }
        template_path = os.path.join(self._get_template_folder_path(),
                                     file_name)
        output_path = os.path.join(destination, project_name + '.yaml')
        self._render_file(template_path, output_path, options)


class DjangoSourceFileGenerator(_FileGenerator):
    """The class to create all necessary Django source files."""

    def __init__(self):
        self.django_file_generator = _DjangoFileGenerator()
        self.docker_file_generator = _DockerfileGenerator()
        self.dependency_file_generator = _DependencyFileGenerator()
        self.settings_file_generator = _SettingsFileGenerator()
        self.yaml_file_generator = _YAMLFileGenerator()
        self.app_engine_file_generator = _AppEngineFileGenerator()

    def _generate_django_source_files(self,
                                      project_id: str,
                                      project_name: str,
                                      app_names: List[str],
                                      destination: str,
                                      database_name: str,
                                      cloud_storage_bucket_name: str,
                                      cloud_sql_connection: str):
        """Generate Django project and settings file.

        Args:
            project_id: Your GCP project id. This can be got from your GCP
                console.
            project_name: Name of your Django project.
            app_names: A list of apps you want to create in your project.
            destination: The destination directory path to put your Django
                project.
            database_name: Name of your cloud database.
            cloud_storage_bucket_name: Google Cloud Storage bucket name to
                serve static content.
            cloud_sql_connection: Connection string to allow the django app
                to connect to the cloud sql proxy.
        """

        self.django_file_generator.generate_project_files(
            project_name, destination)

        self.django_file_generator.generate_admin_files(project_id,
                                                        project_name,
                                                        destination)

        self.django_file_generator.generate_templates_files(destination)
        self.django_file_generator.generate_static_files(destination)
        for app_name in app_names:
            self.django_file_generator.generate_app_files(app_name, destination)
        self.settings_file_generator.generate_new(
            project_id, project_name, destination, cloud_sql_connection,
            database_name, cloud_storage_bucket_name)

    def setup_django_environment(self,
                                 destination: str,
                                 project_name: str,
                                 database_user: str,
                                 database_password: str):
        """Setup Django environment.

        This makes Django command calls afterwards affect the newly generated
        project.

        Args:
            destination: Absolute directory path to put your Django project.
            project_name: Name of your Django project.
            database_user: The name of the database user. By default it is
                "postgres". This is required for Django app to access database.
            database_password: The database password to set.
        """
        os.environ.setdefault('DATABASE_USER', database_user)
        os.environ.setdefault('DATABASE_PASSWORD', database_password)
        sys.path.append(destination)
        os.environ['DJANGO_SETTINGS_MODULE'] = '{}.remote_settings'.format(
            project_name)
        django.setup()

    def generate_all_source_files(self,
                                  project_id: str,
                                  project_name: str,
                                  app_names: List[str],
                                  destination: str,
                                  database_user: str,
                                  database_password: str,
                                  cloud_storage_bucket_name:
                                  Optional[str] = None,
                                  cloudsql_secrets: Optional[List[str]] = None,
                                  django_secrets: Optional[List[str]] = None,
                                  instance_name: Optional[str] = None,
                                  database_name: Optional[str] = None,
                                  region: Optional[str] = 'us-west1',
                                  image_tag: Optional[str] = None):
        """Generate all source files of a Django app to be deployed to GKE.

        Args:
            project_id: Your GCP project id. This can be got from your GCP
                console.
            project_name: Name of your Django project.
            app_names: A list of apps you want to create in your project.
            destination: The destination directory path to put your Django
                project.
            database_user: The name of the database user. By default it is
                "postgres". This is required for Django app to access database.
            database_password: The database password to set.
            cloud_storage_bucket_name: Google Cloud Storage bucket name to
                serve static content.
            cloudsql_secrets: A list of secrets needed by cloud sql proxy
                container.
            django_secrets: A list of secrets needed by Django app
                container.
            instance_name: The name of cloud sql instance for database or the
                Django project. The default value for instance_name should be
                the project name.
            database_name: Name of your cloud database.
            region: Where to host the Django project.
            image_tag: A customized docker image tag used in integration tests.
        """

        # Create the folder if not exist.
        destination = os.path.abspath(os.path.expanduser(destination))
        os.makedirs(destination, exist_ok=True)

        # This string is used by cloud sql proxy and specifies how to connect to
        # your cloud sql instance.
        instance_name = instance_name or project_name + '-instance'
        cloud_sql_connection_string = (
            '{}:{}:{}'.format(project_id, region, instance_name))

        self._generate_django_source_files(project_id, project_name, app_names,
                                           destination, database_name,
                                           cloud_storage_bucket_name,
                                           cloud_sql_connection_string)
        self.docker_file_generator.generate(project_name, destination)
        self.dependency_file_generator.generate(destination)

        self.yaml_file_generator.generate(destination, project_name, project_id,
                                          instance_name, region, image_tag,
                                          cloudsql_secrets, django_secrets)
        self.setup_django_environment(
            destination, project_name, database_user, database_password)
        self.app_engine_file_generator.generate(project_name,
                                                destination,
                                                database_password)

    def generate_missing_source_files(self,
                                      project_id: str,
                                      project_name: str,
                                      destination: str,
                                      database_user: str,
                                      database_password: str,
                                      cloud_storage_bucket_name:
                                      Optional[str] = None,
                                      cloudsql_secrets:
                                      Optional[List[str]] = None,
                                      django_app_secrets:
                                      Optional[List[str]] = None,
                                      instance_name: Optional[str] = None,
                                      database_name: Optional[str] = None,
                                      region: Optional[str] = 'us-west1',
                                      image_tag: Optional[str] = None):
        """Generate all source files of a Django app to be deployed to GKE.

        Args:
            project_id: Your GCP project id. This can be got from your GCP
                console.
            project_name: Name of your Django project.
            destination: The destination directory path to put your Django
                project.
            database_user: The name of the database user. By default it is
                "postgres". This is required for Django app to access database.
            database_password: The database password to set.
            cloud_storage_bucket_name: Google Cloud Storage bucket name to
                serve static content.
            cloudsql_secrets: A list of secrets needed by cloud sql proxy
                container.
            django_app_secrets: A list of secrets needed by Django app
                container.
            instance_name: The name of cloud sql instance for database or the
                Django project. The default value for instance_name should be
                the project name.
            database_name: Name of your cloud database.
            region: Where to host the Django project.
            image_tag: A customized docker image tag used in integration tests.
        """
        destination = os.path.abspath(os.path.expanduser(destination))
        self.settings_file_generator.generate_from_existing(
            project_id, project_name, destination, database_name,
            cloud_storage_bucket_name)

        self.docker_file_generator.generate(project_name, destination)

        # TODO: Generate requirements.txt based on existing file.
        self.dependency_file_generator.generate(destination)
        self.yaml_file_generator.generate(destination, project_name, project_id,
                                          instance_name, region, image_tag,
                                          cloudsql_secrets, django_app_secrets)
        self.setup_django_environment(
            destination, project_name, database_user, database_password)
