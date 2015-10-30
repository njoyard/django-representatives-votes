from setuptools import setup, find_packages


setup(
    name='import-parltrack-votes',
    version='0.0.1',
    description='Base app for importing parltrack votes',
    author='Arnaud Fabre',
    author_email='webmaster@memopol.org',
    url='https://github.com/political-memory/import-parltrack-votes.git'
    packages=find_packages(),
    include_package_data=True,
    license='GPLv3',
    keywords='django government parliament',
    classifiers=[
        'Development Status :: 1 - Alpha/Planning',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
