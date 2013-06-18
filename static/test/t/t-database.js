describe('database', function () {
  describe('Table', function () {
    it('should notify on change', function () {
      var s = new sdr.events.Scheduler(window);
      var t = new sdr.database.Table();
      var l = jasmine.createSpy();
      l.scheduler = s;
      t.n.listen(l);
      t.add({
        type: 'channel',
        freq: 100e6
      });
      waitsFor(function() {
        return l.calls.length;
      }, 'notification received', 100);
      runs(function() {
        expect(l).toHaveBeenCalledWith();
      });
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
