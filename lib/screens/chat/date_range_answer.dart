import 'package:flutter/material.dart';

import '../../theme/theme.dart';

const List<String> _months = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/// The most days the planner will build for. graph.py's MAX_TRIP_DAYS.
const int kMaxTripDays = 7;

/// Formats a picked range exactly as the backend's parser expects.
///
/// This is a contract, not a display string. `graph._PICKED_DATES_RE` matches
///
///   ^([A-Za-z]+ \d{1,2}, \d{4})(?:\s+to\s+([A-Za-z]+ \d{1,2}, \d{4}))?$
///
/// strictly and treats anything else as hand-typed, bouncing the traveller
/// back to the calendar. Abbreviating the month, dropping the year, or using
/// a dash instead of " to " breaks the dates question outright — the backend
/// derives both the start date and the inclusive day count from this string.
String formatDateRange(DateTimeRange range) {
  String one(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  final start = one(range.start);
  return range.start == range.end ? start : '$start to ${one(range.end)}';
}

/// Opens the calendar and returns the answer to send, or null if dismissed.
///
/// The dates question is answered by this picker and never by typing, which
/// is why the question's wording omits "or how many days?" — a typed duration
/// is exactly what the backend rejects.
Future<String?> pickTravelDates(BuildContext context) async {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);

  final range = await showDateRangePicker(
    context: context,
    firstDate: today,
    lastDate: DateTime(now.year + 2, now.month, now.day),
    helpText: 'Select your travel dates',
    saveText: 'Done',
  );
  if (range == null) return null;

  // The picker has no length limit of its own, so a 3-week range would sail
  // through to a planner that only builds 7 days. Catching it here keeps the
  // rejection next to the calendar the traveller just used.
  final days = range.end.difference(range.start).inDays + 1;
  if (days > kMaxTripDays) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Trips can be up to $kMaxTripDays days — '
              'pick a shorter range.'),
        ),
      );
    }
    return null;
  }

  return formatDateRange(range);
}

/// The calendar affordance shown under the composer while the buddy is
/// waiting on `travel_dates`.
class DateRangeAnswerBar extends StatelessWidget {
  const DateRangeAnswerBar({super.key, required this.onPick});

  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: SizedBox(
        width: double.infinity,
        child: OutlinedButton.icon(
          onPressed: onPick,
          icon: const Icon(Icons.calendar_month_rounded, size: 18),
          label: const Text('Pick your dates'),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.primary,
            side: const BorderSide(color: AppColors.primary),
            minimumSize: const Size.fromHeight(44),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(AppRadii.md),
            ),
            textStyle: AppTextStyles.bodyMedium
                .copyWith(fontWeight: FontWeight.w700),
          ),
        ),
      ),
    );
  }
}
