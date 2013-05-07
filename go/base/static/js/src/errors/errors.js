(function(exports) {
  var GoError = exports.GoError = function(message) {
    if (message) { this.message = message; }
  };

  // Creates a sub-error constructor from 'this' error constructor
  GoError.suberror = function(name, message) {
    var NewError = function(message) { GoError.call(this, message); };

    // provides the 'e instanceof SomeError' magic we need
    var proto = Object.create(this.prototype);

    proto.name = name;
    if (message) { proto.message = message; }
    NewError.prototype = proto;

    // allow further sub-error creation
    NewError.suberror = GoError.suberror;

    return NewError;
  };

  // We set the [[Prototype]] to Error.prototype so that we can do this with
  // all our errors: `e instanceof Error`
  GoError.prototype = _.extend(Object.create(Error.prototype), {
    name: 'GoError',
    toString: function() {
      return '['
        + this.name
        + (this.message ? ': ' + this.message : '')
        + ']';
    }
  });
})(go.errors = {});
