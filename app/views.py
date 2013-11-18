import bson
import calendar
import datetime
import json
from bson import json_util

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import AnonymousUserMixin, current_user, login_required, login_user, logout_user
import pymongo

from app import app, login_manager, db, TaskStatus
from app.sources.source import Source
from user import User, authenticate_user
from forms import LoginForm, DeleteProjectForm, NewProjectForm, AddSourceTypeForm, AddEventForm, DeleteSourceForm, DeleteEventForm, make_source_form

@app.route('/')
def index():
    return render_template('wrapper.html', content='Home page')

# User views

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm(request.form)
    if form.validate_on_submit():
        user = authenticate_user(form.email.data, form.password.data)
        if not user.is_authenticated():
            return redirect(url_for('login'))
        login_user(user)
        return redirect(request.args.get('next') or url_for('index'))
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@login_manager.user_loader
def load_user(userid):
    '''Callback for flask-login.'''
    u = db.users.find_one({'username':userid})
    if u == None:
        return AnonymousUserMixin()
    return User(u['email'], userid, userid)

# Project views

@app.route('/projects')
@app.route('/projects/<username>')
def projects(username=None):
    if username == None:
        projects = list(db.projects.find())
    else:
        projects = list(db.projects.find({'owner':username}))
    return render_template('projects.html', projects=projects, username=username)

@app.route('/<username>/<project_name>')
def project(username, project_name):
    project = db.projects.find_one({'name':project_name, 'owner':username})
    if project == None:
        flash("Sorry, that project doesn't exist.")
        return render_template('wrapper.html')
    sources = db.sources.find({'project_id':project['_id'], 'status':TaskStatus.COMPLETE})
    # Create d3-friendly json
    # There's probably a better way to do this, like a "group by" in sql -Ed
    data = []
    for source in sources:
        query = {'source_id':source['_id']}
        fields = {'_id':False, 'source_id':False, 'project_id':False}
        source_data = {
            'name':source['label']
            , 'values':[{'date':r['date'], 'value':r['value'], 'raw':r['raw'], 'label':r['label'], 'words':r.get('words', [])} for r in db.results.find(query, fields=fields, sort=[('date', pymongo.ASCENDING)])]
        }
        data.append(source_data)
    events = db.events.find({'project_id':project['_id']}, fields= {'_id':False, 'project_id':False, 'date':False})
    event_data = []
    for e in events:
        event_data.append = {'date':e['date'], 'label':e['label'], 'timestamp':e['timestamp']}
    return render_template('project.html', project=project, data=json.dumps(data), events=json.dumps(event_data))

@app.route('/<username>/<project_name>/settings', methods=['GET', 'POST'])
def project_settings(username, project_name):
    if current_user.name != username:
        abort(403)
    project = db.projects.find_one({'name':project_name, 'owner':username})
    source_list = list(db.sources.find({'project_id':project['_id']}))
    delete_source_forms = []
    for source in source_list:
        form = DeleteSourceForm(prefix="delete_source")
        form.source_id.data = source['_id']
        form.source_name.data = source['label']
        delete_source_forms.append(form)
    delete_form = DeleteProjectForm(prefix="delete")
    if delete_form.name.data and delete_form.validate_on_submit():
        if project_name == delete_form.name.data:
            db.projects.remove({'name':delete_form.name.data})
            flash('Project deleted.')
            return redirect(url_for('index'))
        else:
            flash('Project name did not match.')
    add_type_form = AddSourceTypeForm(prefix="add_source_type")
    if not add_type_form.source_type.data == 'None':
        return redirect(url_for('add_source', username=username, project_name=project_name, source_name=add_type_form.source_type.data))
    add_event_form = AddEventForm(prefix="add_event")
    if add_event_form.event_label.data and add_event_form.validate_on_submit():
        dt = datetime.datetime.strptime(add_event_form.event_date.data, '%Y-%m-%d')
        timestamp = calendar.timegm(dt.timetuple())
        db.events.insert({
            'project_id': project['_id']
            , 'label': add_event_form.event_label.data
            , 'date': add_event_form.event_date.data
            , 'timestamp': timestamp
        });
    delete_source_form = DeleteSourceForm(prefix="delete_source")
    if delete_source_form.source_id.data and delete_source_form.validate_on_submit():
        # Delete data associated with that source
        source_id = bson.objectid.ObjectId(delete_source_form.source_id.data)
        db.sources.remove({'_id': source_id})
        db.raw.remove({'source_id': source_id})
        db.transformed.remove({'source_id': source_id})
        db.words.remove({'source_id': source_id})
        db.results.remove({'source_id': source_id})
        # Update the source list
        source_list = list(db.sources.find({'project_id':project['_id']}))
        delete_source_forms = []
        for source in source_list:
            delete_source_forms.append(DeleteSourceForm(prefix="delete_source", source_id=source['_id'], source_name=source['label']))
    delete_event_form = DeleteEventForm(prefix="delete_event")
    if delete_event_form.event_id.data and delete_event_form.validate_on_submit():
        event_id = bson.objectid.ObjectId(delete_event_form.event_id.data)
        db.events.remove({'_id':event_id, 'project_id':project['_id']})
    events = list(db.events.find({'project_id': project['_id']}, sort=[('date', pymongo.ASCENDING)]))
    delete_event_forms = []
    for event in events:
        form = DeleteEventForm(prefix="delete_event")
        form.event_id.data = event['_id']
        form.event_label.data = event['label']
        delete_event_forms.append(form)
    return render_template(
        'project-settings.html'
        , project=project
        , events=events
        , delete_form=delete_form
        , add_type_form=add_type_form
        , add_event_form=add_event_form
        , sources=source_list
        , delete_source_forms=delete_source_forms
        , delete_event_forms=delete_event_forms)

@app.route('/<username>/<project_name>/add-source/<source_name>', methods=['GET', 'POST'])
@login_required
def add_source(username, project_name, source_name):
    project = db.projects.find_one({'name':project_name, 'owner':username})
    source = Source.sources[source_name]
    CreateForm = source.create_form()
    create_form = CreateForm()
    if create_form.validate_on_submit():
        s = source.create(request, username, project_name)
        s['project_id'] = project['_id']
        db.sources.insert(s)
        return redirect(url_for('project_settings', project_name=project_name, username=username))
    return render_template(
        'add-source.html'
        , project=project
        , source_name=source_name
        , create_form=create_form)

@app.route('/new-project', methods=['GET', 'POST'])
@login_required
def new_project():
    form = NewProjectForm(request.form)
    if form.validate_on_submit():
        project = {
            'name': form.name.data
            , 'start': form.start_date.data
            , 'end': form.end_date.data
            , 'keywords': [k.strip() for k in form.keywords.data.split(',')]
            , 'owner' : current_user.id
        }
        existing = db.projects.find_one({'name':form.name.data, 'owner':current_user.id})
        if existing == None:
            db.projects.insert(project)
            return redirect(url_for('project', username=current_user.name, project_name=form.name.data))
        else:
            flash('Sorry, that name is already taken.')
    return render_template('new-project.html', form=form)

