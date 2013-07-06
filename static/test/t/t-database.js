'use strict';

describe('database', function () {
  var s;
  beforeEach(function () {
    s = new sdr.events.Scheduler(window);
  });
  function createListenerSpy() {
    var l = jasmine.createSpy();
    l.scheduler = s;
    return l;
  }
  function expectNotification(l) {
    // TODO: we could make a timeless test by mocking the scheduler
    waitsFor(function() {
      return l.calls.length;
    }, 'notification received', 100);
    runs(function() {
      expect(l).toHaveBeenCalledWith();
    });
  }
  var dummyRecord = Object.freeze({
    type: 'channel',
    freq: 100e6
  });
  
  describe('Table', function () {
    it('should notify on record addition', function () {
      var t = new sdr.database.Table();
      var l = createListenerSpy();
      t.n.listen(l);
      t.add(dummyRecord);
      expectNotification(l);
    });
    
    it('should notify on record modification', function () {
      var t = new sdr.database.Table();
      var l = createListenerSpy();
      var r = t.add({
        type: 'channel',
        freq: 100e6
      });
      t.n.listen(l);
      r.freq = 120e6;
      expectNotification(l);
    });
  });

  describe('Union', function () {
    it('should notify on member change', function () {
      var t = new sdr.database.Table();
      var u = new sdr.database.Union();
      u.add(t);
      var l = createListenerSpy();
      u.n.listen(l);
      t.add(dummyRecord);
      expectNotification(l);
    });
  });
  
  describe('CSV parser', function () {
    // I generally hold to the 'test only the public interface', but this is sufficiently hairy but doesn't otherwise have a reasonable exported interface (entire CSV files would make the test cases needlessly large).
    var parseCSVLine = sdr.database._parseCSVLine;
    function t(csv, out) {
      it('should parse: ' + csv, function () {
        expect(parseCSVLine(csv)).toEqual(out);
      });
    }
    t('', ['']);
    t(',', ['', '']);
    t('a,b,', ['a', 'b', '']);
    t('"a,b","c,d"', ['a,b', 'c,d']);
    t('a,"b""c""d",e', ['a', 'b"c"d', 'e']);
    t('a,"""bcd""",e', ['a', '"bcd"', 'e']);
  });
});
