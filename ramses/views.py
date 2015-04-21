import logging

from nefertari.view import BaseView as NefertariBaseView
from nefertari.json_httpexceptions import (
    JHTTPCreated, JHTTPOk, JHTTPNotFound)


log = logging.getLogger(__name__)

"""
Maps of {HTTP_method: neferteri view method name}

"""
collection_methods = {
    'get':      'index',
    'post':     'create',
    'put':      'update_many',
    'patch':    'update_many',
    'delete':   'delete_many',
}
item_methods = {
    'get':      'show',
    'post':     'create',
    'put':      'update',
    'patch':    'update',
    'delete':   'delete',
}


class BaseView(NefertariBaseView):
    """ Base view class for other all views that defines few helper methods.

    Use `self.get_collection` and `self.get_item` to get access to set of
    objects and object respectively which are valid at current level.
    """
    def __init__(self, *args, **kwargs):
        super(BaseView, self).__init__(*args, **kwargs)
        if self.request.method == 'GET':
            self._params.process_int_param('_limit', 20)

    def resolve_kw(self, kwargs):
        """ Resolve :kwargs: like `story_id: 1` to the form of `id: 1`.

        """
        return {k.split('_', 1)[1]: v for k, v in kwargs.items()}

    def _location(self, obj):
        """ Get location of the `obj`

        Arguments:
            :obj: self._model_class instance.
        """
        id_name = self._resource.id_name
        field_name = id_name.split('_', 1)[1]
        return self.request.route_url(
            self._resource.uid,
            **{id_name: getattr(obj, field_name)})

    def _parent_queryset(self):
        """ Get queryset of parent view.

        Generated queryset is used to run queries in the current level view.
        """
        parent = self._resource.parent
        if hasattr(parent, 'view'):
            req = self.request.blank(self.request.path)
            req.registry = self.request.registry
            req.matchdict = {
                parent.id_name: self.request.matchdict.get(parent.id_name)}
            parent_view = parent.view(parent.view._factory, req)
            obj = parent_view.get_item(**req.matchdict)
            if isinstance(self, ItemSubresourceBaseView):
                return
            prop = self._resource.collection_name
            return getattr(obj, prop, None)

    def get_collection(self, **kwargs):
        """ Get objects collection taking into account generated queryset
        of parent view.

        This method allows to work with nested resources properly. Thus queryset
        returned by this method will be a subset of parent view's queryset, thus
        filtering out objects that don't belong to parent object.
        """
        self._params.update(kwargs)
        objects = self._parent_queryset()
        if objects is not None:
            return self._model_class.filter_objects(objects, **self._params)
        return self._model_class.get_collection(**self._params)

    def get_item(self, **kwargs):
        """ Get collection item taking into account generated queryset
        of parent view.

        This method allows to work with nested resources properly. Thus item
        returned by this method will belong to parent view's queryset, thus
        filtering out objects that don't belong to parent object.
        """
        kwargs = self.resolve_kw(kwargs)
        objects = self._parent_queryset()
        if objects is not None:
            return self._model_class.filter_objects(
                objects, first=True, **kwargs)
        return self._model_class.get_resource(**kwargs)


class CollectionView(BaseView):
    """ View that works with database and implements handlers for all
    available CRUD operations.

    """
    def index(self, **kwargs):
        return self.get_collection()

    def show(self, **kwargs):
        return self.get_item(**kwargs)

    def create(self, **kwargs):
        obj = self._model_class(**self._params).save()
        return JHTTPCreated(
            location=self._location(obj),
            resource=obj.to_dict(request=self.request))

    def update(self, **kwargs):
        obj = self.get_item(**kwargs)
        obj.update(self._params)
        return JHTTPOk('Updated', location=self._location(obj))

    def delete(self, **kwargs):
        self._model_class._delete(**self.resolve_kw(kwargs))
        return JHTTPOk('Deleted')

    def delete_many(self, **kwargs):
        objects = self.get_collection()
        count = objects.count()

        if self.needs_confirmation():
            return objects

        self._model_class._delete_many(objects)
        return JHTTPOk('Deleted %s %s(s) objects' % (
            count, self._model_class.__name__))

    def update_many(self, **kwargs):
        _limit = self._params.pop('_limit', None)
        objects = self.get_collection(_limit=_limit)
        self._model_class._update_many(objects, **self._params)
        return JHTTPOk('Updated %s %s(s) objects' % (
            objects.count(), self._model_class.__name__))


class ESBaseView(BaseView):
    """ Elasticsearch base view that fetches data from ES.

    Implements analogues of _parent_queryset, get_collection, get_item
    fetching data from ES instead of database.

    Use `self.get_collection_es` and `self.get_item_es` to get access
    to set of objects and object respectively which are valid at current level.
    """
    def _get_raw_terms(self):
        search_params = []
        if 'q' in self._params:
            search_params.append(self._params.pop('q'))
        _raw_terms = ' AND '.join(search_params)
        return _raw_terms

    def _parent_queryset_es(self):
        """ Get queryset (list of object IDs) of parent view.

        Generated queryset is used to run queries in the current level
        view.
        """
        parent = self._resource.parent
        if hasattr(parent, 'view'):
            req = self.request.blank(self.request.path)
            req.registry = self.request.registry
            req.matchdict = {
                parent.id_name: self.request.matchdict.get(parent.id_name)}
            parent_view = parent.view(parent.view._factory, req)
            obj = parent_view.get_item_es(**req.matchdict)
            prop = self._resource.collection_name
            objects_ids = getattr(obj, prop, None)
            if objects_ids is not None:
                objects_ids = [str(id_) for id_ in objects_ids]
            return objects_ids

    def get_collection_es(self, **kwargs):
        """ Get ES objects collection taking into account generated queryset
        of parent view.

        This method allows to work with nested resources properly. Thus queryset
        returned by this method will be a subset of parent view's queryset, thus
        filtering out objects that don't belong to parent object.
        """
        from nefertari.elasticsearch import ES
        es = ES(self._model_class.__name__)
        objects_ids = self._parent_queryset_es()

        if objects_ids is not None:
            if not objects_ids:
                return []
            self._params['id'] = objects_ids
        return es.get_collection(
            _raw_terms=self._get_raw_terms(),
            **self._params)

    def get_item_es(self, **kwargs):
        """ Get ES collection item taking into account generated queryset
        of parent view.

        This method allows to work with nested resources properly. Thus item
        returned by this method will belong to parent view's queryset, thus
        filtering out objects that don't belong to parent object.
        """
        from nefertari.elasticsearch import ES
        es = ES(self._model_class.__name__)
        item_id = str(kwargs.get(self._resource.id_name))
        objects_ids = self._parent_queryset_es()

        if (objects_ids is not None) and (item_id not in objects_ids):
            raise JHTTPNotFound('{}(id={}) resource not found'.format(
                self._model_class.__name__, item_id))

        kwargs = {self._resource.id_name: item_id}
        kwargs = self.resolve_kw(kwargs)
        kwargs['_limit'] = 1
        kwargs['__raise_on_empty'] = True
        return es.get_collection(**kwargs)[0]


class ESCollectionView(ESBaseView, CollectionView):
    """ View that reads data from ES.

    Write operations are inherited from :CollectionView:
    """
    def index(self, **kwargs):
        return self.get_collection_es(**kwargs)

    def show(self, **kwargs):
        return self.get_item_es(**kwargs)


class ItemSubresourceBaseView(BaseView):
    """ Base class for all subresources of collection item resource, that
    don't represent a collection. E.g. /users/{id}/profile, where 'profile'
    is a singular resource or /users/{id}/some_action, where 'some_action'
    action may be performed when requesting this route.

    Subclass ItemSubresourceBaseView in your project when you want to define
    subroute and view of a item route defined in RAML and generated by ramses.
    Use `self.get_item` to get an object on which actions are being performed.

    Moved into a separate class so all item subresources have a common
    base class, thus making checks like `isinstance(view, baseClass)` easier.
    """
    pass


class ItemAttributeView(ItemSubresourceBaseView):
    """ View used to work with attribute resources.

    Attribute resources represent field: ListField, DictField.

    You may subclass ItemAttributeView in your project when you want to define
    custom attribute subroute and view of a item route defined in RAML and
    generated by ramses.
    """
    def __init__(self, *args, **kw):
        super(ItemAttributeView, self).__init__(*args, **kw)
        self.attr = self.request.path.split('/')[-1]
        self.value_type = None
        self.unique = True

    def index(self, **kwargs):
        obj = self.get_item(**kwargs)
        return getattr(obj, self.attr)

    def create(self, **kwargs):
        obj = self.get_item(**kwargs)
        obj.update_iterables(
            self._params, self.attr,
            unique=self.unique,
            value_type=self.value_type)
        return JHTTPCreated(resource=getattr(obj, self.attr, None))


class ItemSingularView(ItemSubresourceBaseView):
    """ View used to work with singular resources.

    Singular resources represent one-to-one relationship. E.g. users/1/profile.

    You may subclass ItemSingularView in your project when you want to define
    custom singular subroute and view of a item route defined in RAML and
    generated by ramses.
    """
    def __init__(self, *args, **kw):
        super(ItemSingularView, self).__init__(*args, **kw)
        self.attr = self.request.path.split('/')[-1]

    def show(self, **kwargs):
        parent_obj = self.get_item(**kwargs)
        return getattr(parent_obj, self.attr)

    def create(self, **kwargs):
        parent_obj = self.get_item(**kwargs)
        obj = self._singular_model(**self._params).save()
        parent_obj.update({self.attr: obj})
        return JHTTPCreated(resource=getattr(obj, self.attr, None))

    def update(self, **kwargs):
        parent_obj = self.get_item(**kwargs)
        obj = getattr(parent_obj, self.attr)
        obj.update(self._params)
        return JHTTPCreated(resource=getattr(obj, self.attr, None))

    def delete(self, **kwargs):
        parent_obj = self.get_item(**kwargs)
        parent_obj.update({self.attr: None})
        return JHTTPOk('Deleted')


def generate_rest_view(model_cls, attrs=None, es_based=True,
                       attr_view=False, singular=False):
    """ Generate REST view for model class.

    Arguments:
        :model_cls: Generated DB model class.
        :attr: List of strings that represent names of view methods, new
            generated view should support. Not supported methods are replaced
            with property that raises AttributeError to display MethodNotAllowed
            error.
        :es_based: Boolean indicating if generated view should read from
            elasticsearch. If True - collection reads are performed from
            elasticsearch; database is used for reads instead. Defaults to True.
        :attr_view: Boolean indicating if ItemAttributeView should be used as a
            base class for generated view.
        :singular: Boolean indicating if ItemSingularView should be used as a
            base class for generated view.
    """
    from nefertari.engine import JSONEncoder
    valid_attrs = collection_methods.values() + item_methods.values()
    missing_attrs = set(valid_attrs) - set(attrs)

    if singular:
        base_view_cls = ItemSingularView
    elif attr_view:
        base_view_cls = ItemAttributeView
    elif es_based:
        base_view_cls = ESCollectionView
    else:
        base_view_cls = CollectionView

    def _attr_error(*args, **kwargs):
        raise AttributeError

    class RESTView(base_view_cls):
        _json_encoder = JSONEncoder
        _model_class = model_cls

    for attr in missing_attrs:
        setattr(RESTView, attr, property(_attr_error))

    return RESTView
