import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/event.dart';

void main() {
  test('the category chips follow the Korea Tourism Organization classification', () {
    // EngService2 returns `lclsSystm1`~`3`; its `cat1`~`cat3` fields come back
    // empty, so EV01/EV02/EV03 is the only grouping the data actually carries.
    // These replaced nine ticket-site genre tabs — Seoul has ~79 events in
    // total, which more chips than this would spread too thin to fill a grid.
    expect(kEventCategories, [
      'All',
      'Festivals',
      'Performances',
      'Exhibitions',
    ]);
  });

  test('the default tab is one of the chips', () {
    // EventsScreen opens on this category before anything is tapped; a value
    // outside the list leaves every chip unselected and the backend serving
    // the unfiltered list without saying so.
    expect(kEventCategories, contains(kDefaultEventCategory));
  });

  test("backend's chip map covers exactly these labels", () {
    // The Dart list and backend/api.py's _EV_CHIP are edited separately, and a
    // label present on only one side fails silently: _chip_filter does not
    // recognise it and returns everything, so the chip looks like it did
    // nothing rather than erroring.
    final api = File('backend/api.py');
    if (!api.existsSync()) {
      markTestSkipped('backend/api.py not present in this checkout');
      return;
    }

    final block = RegExp(r'_EV_CHIP = \{(.*?)\n\}', dotAll: true)
        .firstMatch(api.readAsStringSync());
    expect(block, isNotNull, reason: '_EV_CHIP not found in backend/api.py');

    final keys = RegExp('"([^"]+)":')
        .allMatches(block!.group(1)!)
        .map((m) => m.group(1)!)
        .toList();

    // 'All' is deliberately absent from the backend map — it means "no filter".
    expect(keys, kEventCategories.sublist(1),
        reason: 'chip labels drifted between Dart and backend/api.py');
  });
}
