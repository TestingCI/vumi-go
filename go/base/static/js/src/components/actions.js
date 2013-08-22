// go.components.actions
// =====================
// Reusable components for UI actions

(function(exports) {
  var Eventable = go.components.structures.Eventable;

  var PopoverView = go.components.views.PopoverView;

  var PopoverNotifier = PopoverView.extend({
    popoverOptions: {trigger: 'manual'},
    target: function() { return this.action.$el; },

    successMsg: function() { return this.action.name + ' successful!'; },
    errorMsg: function() { return this.action.name + ' failed :/'; },

    initialize: function(options) {
      PopoverNotifier.__super__.initialize.call(this, options);

      this.action = options.action;
      if (options.successMsg) { this.successMsg = options.successMsg; }
      if (options.errorMsg) { this.errorMsg = options.errorMsg; }
      go.utils.bindEvents(this.bindings, this);
    },

    bindings: {
      'invoke action': function() {
        this.$el.text('loading...');
        this.show();
      },

      'success action': function() {
        this.$el.text(_(this).result('successMsg'));
      },

      'error action': function() {
        this.$el.text(_(this).result('errorMsg'));
      },
    }
  });

  var ActionView = Backbone.View.extend({
    name: 'Unnamed',

    useNotifier: false,
    notifierOptions: {type: PopoverNotifier},

    constructor: function(options) {
      options = options || {};
      ActionView.__super__.constructor.call(this, options);

      this.name = options.name || this.name;

      if (options.notifier) { this.useNotifier = true; }
      this.initNotifier(options.notifier);
    },

    initNotifier: function(options) {
      if (!this.useNotifier) { return; }

      options = _(options || {}).defaults(
        this.notifierOptions,
        {action: this});

      this.notifier = new options.type(options);
    },

    invoke: function() {},

    events: {
      'click': function(e) {
        this.invoke();
        e.preventDefault();
      }
    },
  });

  // View for saving a model to the server side
  var SaveActionView = ActionView.extend({
    initialize: function(options) {
      if (options.sessionId) { this.sessionId = options.sessionId; }
    },

    invoke: function() {
      var options = {
        success: function() { this.trigger('success'); }.bind(this),
        error: function() { this.trigger('error'); }.bind(this)
      };

      if (this.sessionId) { options.sessionId = this.sessionId; }
      this.model.save({}, options);
      this.trigger('invoke');

      return this;
    }
  });

  // View for resetting a model to its initial state
  var ResetActionView = ActionView.extend({
    initialize: function() {
      this.backup = this.model.toJSON();
    },

    invoke: function() {
      this.model.set(this.backup);
      this.trigger('invoke');
      return this;
    }
  });

  // View that invokes its action by sending an ajax request to the server side
  //
  // NOTE: Ideally, only our models should be interacting with the server side.
  // This view is a temporary solution, and should be replaced as soon as we
  // are in a position where the data on our pages can be managed by models
  // syncing with our api.
  var CallActionView = ActionView.extend({
    url: function() { return this.$el.attr('data-url'); },

    data: {},

    ajax: {},

    constructor: function(options) {
      CallActionView.__super__.constructor.call(this, options);

      if (options.url) { this.url = options.url; }
      if (options.data) { this.data = options.data; }
      if (options.ajax) { this.ajax = options.ajax; }
    },

    invoke: function() {
      var url = _(this).result('url');

      var ajax = _({
        type: 'post',
        data: _(this).result('data')
      }).extend(
        url ? {url: url} : {},
        _(this).result('ajax'));

      var success = ajax.success,
          error = ajax.error;

      ajax.success = function() {
        if (success) { success.apply(this, arguments); }
        this.trigger('success');
      }.bind(this);

      ajax.error = function() {
        if (error) { error.apply(this, arguments); }
        this.trigger('error');
      }.bind(this);

      $.ajax(ajax);
      this.trigger('invoke');

      return this;
    }
  });

  _(exports).extend({
    ActionView: ActionView,
    SaveActionView: SaveActionView,
    ResetActionView: ResetActionView,
    CallActionView: CallActionView,

    PopoverNotifier: PopoverNotifier
  });
})(go.components.actions = {});
