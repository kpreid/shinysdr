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
});
