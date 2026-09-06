import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/screens/chat/date_range_answer.dart';

void main() {
  group('formatDateRange is a backend contract, not a display string', () {
    // graph._PICKED_DATES_RE:
    //   ^([A-Za-z]+ \d{1,2}, \d{4})(?:\s+to\s+([A-Za-z]+ \d{1,2}, \d{4}))?$
    // Anything it does not match is treated as hand-typed and bounced back to
    // the calendar, so these assertions guard the wire format itself.
    final re = RegExp(
        r'^([A-Za-z]+ \d{1,2}, \d{4})(?:\s+to\s+([A-Za-z]+ \d{1,2}, \d{4}))?$');

    test('a multi-day range matches, with a full month name and year', () {
      final out = formatDateRange(DateTimeRange(
        start: DateTime(2026, 9, 30),
        end: DateTime(2026, 10, 2),
      ));

      expect(out, 'September 30, 2026 to October 2, 2026');
      expect(re.hasMatch(out), isTrue);
    });

    test('a single day collapses to one date, still matching', () {
      final out = formatDateRange(DateTimeRange(
        start: DateTime(2026, 9, 6),
        end: DateTime(2026, 9, 6),
      ));

      expect(out, 'September 6, 2026');
      expect(re.hasMatch(out), isTrue);
    });

    test('the day is never zero-padded', () {
      // "%B %d, %Y" would render "June 05"; the backend parses with strptime
      // but the regex allows 1-2 digits, and the app's own format must match
      // what the picker emitted upstream.
      final out = formatDateRange(DateTimeRange(
        start: DateTime(2026, 6, 5),
        end: DateTime(2026, 6, 5),
      ));

      expect(out, 'June 5, 2026');
      expect(out, isNot(contains('June 05')));
    });

    test('every month is the full English name strptime(%B) expects', () {
      // An abbreviation like "Sep" would still satisfy the regex but fail
      // strptime("%B") on the backend. Checked against the names themselves,
      // not a length rule — May, June and July are legitimately short.
      const full = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ];

      for (var month = 1; month <= 12; month++) {
        final out = formatDateRange(DateTimeRange(
          start: DateTime(2026, month, 1),
          end: DateTime(2026, month, 1),
        ));
        expect(re.hasMatch(out), isTrue, reason: out);
        expect(out.split(' ').first, full[month - 1], reason: out);
      }
    });
  });

  testWidgets('the calendar bar is what the traveller taps', (tester) async {
    var tapped = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: DateRangeAnswerBar(onPick: () => tapped = true),
      ),
    ));

    expect(find.byIcon(Icons.calendar_month_rounded), findsOneWidget);
    await tester.tap(find.text('Pick your dates'));
    expect(tapped, isTrue);
  });
}
