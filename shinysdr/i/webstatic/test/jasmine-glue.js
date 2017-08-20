// Nearly all of this code is from Jasmine boot.js. Open to suggestions for how to get the effects without copying code from Jasmine.
//
// It has been modified to:
//   create a singleton Jasmine environment but not start it onload or define globals
//   be compatible with RequireJS

'use strict';

define(() => {
  const jasmine = jasmineRequire.core(jasmineRequire);
  jasmineRequire.html(jasmine);

  const env = jasmine.getEnv();

  const jasmineInterface = jasmineRequire.interface(jasmine, env);

  // --- begin entirely unmodified code ---
  var queryString = new jasmine.QueryString({
    getWindowLocation: function() { return window.location; }
  });

  var catchingExceptions = queryString.getParam("catch");
  env.catchExceptions(typeof catchingExceptions === "undefined" ? true : catchingExceptions);

  var throwingExpectationFailures = queryString.getParam("throwFailures");
  env.throwOnExpectationFailure(throwingExpectationFailures);

  var random = queryString.getParam("random");
  env.randomizeTests(random);

  var seed = queryString.getParam("seed");
  if (seed) {
    env.seed(seed);
  }

  var htmlReporter = new jasmine.HtmlReporter({
    env: env,
    onRaiseExceptionsClick: function() { queryString.navigateWithNewParam("catch", !env.catchingExceptions()); },
    onThrowExpectationsClick: function() { queryString.navigateWithNewParam("throwFailures", !env.throwingExpectationFailures()); },
    onRandomClick: function() { queryString.navigateWithNewParam("random", !env.randomTests()); },
    addToExistingQueryString: function(key, value) { return queryString.fullStringWithNewParam(key, value); },
    getContainer: function() { return document.body; },
    createElement: function() { return document.createElement.apply(document, arguments); },
    createTextNode: function() { return document.createTextNode.apply(document, arguments); },
    timer: new jasmine.Timer()
  });

  env.addReporter(jasmineInterface.jsApiReporter);
  env.addReporter(htmlReporter);

  var specFilter = new jasmine.HtmlSpecFilter({
    filterString: function() { return queryString.getParam("spec"); }
  });

  env.specFilter = function(spec) {
    return specFilter.matches(spec.getFullName());
  };

  // --- end entirely unmodified code ---

  return Object.freeze({
    ji: jasmineInterface,
    start() {
      htmlReporter.initialize();
      env.execute();
    }
  });
});