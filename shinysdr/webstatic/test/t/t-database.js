'use strict';

describe('database', function () {
  // TODO: duplicated code w/ other tests; move to a common library somewhere
  var s;
  beforeEach(function () {
    s = new shinysdr.events.Scheduler(window);
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
      var t = new shinysdr.database.Table('foo', true);
      var l = createListenerSpy();
      t.n.listen(l);
      t.add(dummyRecord);
      expectNotification(l);
    });
    
    it('should notify from table on record modification', function () {
      var t = new shinysdr.database.Table('foo', true);
      var l = createListenerSpy();
      var r = t.add({
        type: 'channel',
        freq: 100e6
      });
      t.n.listen(l);
      r.freq = 120e6;
      expectNotification(l);
    });

    it('should notify from record on record modification', function () {
      var t = new shinysdr.database.Table('foo', true);
      var l = createListenerSpy();
      var r = t.add({
        type: 'channel',
        freq: 100e6
      });
      r.n.listen(l);
      r.freq = 120e6;
      expectNotification(l);
    });

    it('record should have default values', function () {
      var r = (new shinysdr.database.Table('foo', true)).add({});
      expect(r.writable).toEqual(true);
      expect(r.type).toEqual('channel');
      expect(r.mode).toEqual('?');
      expect(r.freq).toBeNaN();
      expect(r.lowerFreq).toBeNaN();
      expect(r.upperFreq).toBeNaN();
      expect(r.location).toEqual(null);
      expect(r.label).toEqual('');
      expect(r.notes).toEqual('');
    });

    it('record should coerce a location', function () {
      var r = (new shinysdr.database.Table('foo', true)).add({location: ['1', '2']});
      expect(r.location.length).toEqual(2);
      expect(r.location[0]).toEqual(1);
      expect(r.location[1]).toEqual(2);
    });

    it('should report writability', function () {
      expect(new shinysdr.database.Table('writable', true).writable).toBe(true);
      expect(new shinysdr.database.Table('ro', false).writable).toBe(false);
    });

    it('should refuse to add records if not writable', function () {
      expect(function () {
        new shinysdr.database.Table('writable', false).add({});
      }).toThrow('This table is read-only');
    });

    it('should refuse to modify records if not writable', function () {
      var table = new shinysdr.database.Table('writable', false, function(add) {
        add({freq: 0, label: 'foo'});
      });
      expect(table.getAll()[0].writable).toBe(false);
      expect(function () {
        table.getAll()[0].label = 'bar';
      }).toThrow('This record is read-only');
      expect(table.getAll()[0].label).toBe('foo');
    });
  });

  describe('GroupView', function () {
    var t, r1, r2, view;
    beforeEach(function () {
      t = new shinysdr.database.Table('foo', true);
      r1 = t.add({type: 'channel', freq: 100e6, label: 'a'});
      r2 = t.add({type: 'channel', freq: 100e6, label: 'b'});
      view = t.groupSameFreq();
    });
    
    it('should return a grouped record', function () {
      expect(view.getAll().length).toBe(1);
      var r = view.getAll()[0];
      expect(typeof r).toBe('object');
      expect(r.type).toBe('group');
      expect(r.freq).toBe(100e6);
      expect(r.grouped.length).toEqual(2);
      expect(r.grouped).toContain(r1);
      expect(r.grouped).toContain(r2);
    });
    
    it('record should not change and have an inert notifier', function () {
      // We don't actually specifically _want_ to have an immutable group record, but we're testing the current implementation is consistent.
      var r = view.getAll()[0];
      expect(r.n).toBeTruthy();
      var l = createListenerSpy();
      r.n.listen(l);
      r1.freq = 120e6;
      waits(10);
      waits(10);  // cycle event loop a bit
      runs(function() {
        expect(l).not.toHaveBeenCalled();
        expect(r.grouped).toContain(r1);
      });
    });
  });

  describe('Union', function () {
    it('should notify on member change', function () {
      var t = new shinysdr.database.Table('foo', true);
      var u = new shinysdr.database.Union();
      u.add(t);
      var l = createListenerSpy();
      u.n.listen(l);
      t.add(dummyRecord);
      expectNotification(l);
    });
  });
});
