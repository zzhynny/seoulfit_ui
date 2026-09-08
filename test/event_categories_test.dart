import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/event.dart';

void main() {
  test('the category chips are the genres NOL actually has', () {
    // Read off world.nol.com/en/ticket's own nav, in its own order. The list
    // used to carry 'Exhibition' and 'Theater', labels NOL does not use, and
    // omit Play&Stay, Sports and Dance entirely.
    expect(kEventCategories, [
      'Play&Stay',
      'Concert',
      'Musical',
      'Play',
      'Exhibitions',
      'Sports',
      'Dance',
      'Classic',
      'Family',
    ]);
  });

  test('the default tab is one of the chips', () {
    // EventsScreen opens on this category before anything is tapped; a value
    // outside the list leaves every chip unselected and the backend falling
    // back to Musical without saying so.
    expect(kEventCategories, contains(kDefaultEventCategory));
  });

  test("backend's genre map covers exactly these labels", () {
    // The Dart list and backend/api.py's _NOL_GENRE are edited separately, and
    // a label present on only one side fails silently: get_events falls back
    // to Musical, so the tab loads someone else's events rather than erroring.
    final api = File('backend/api.py');
    if (!api.existsSync()) {
      markTestSkipped('backend/api.py not present in this checkout');
      return;
    }

    final block = RegExp(r'_NOL_GENRE = \{(.*?)\n\}', dotAll: true)
        .firstMatch(api.readAsStringSync());
    expect(block, isNotNull, reason: '_NOL_GENRE not found in backend/api.py');

    final keys = RegExp('"([^"]+)":')
        .allMatches(block!.group(1)!)
        .map((m) => m.group(1)!)
        .toSet();

    for (final category in kEventCategories) {
      expect(keys, contains(category.toLowerCase()),
          reason: '$category has no entry in _NOL_GENRE');
    }
  });
}
