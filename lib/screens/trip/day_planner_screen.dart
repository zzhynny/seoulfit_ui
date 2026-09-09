import 'package:flutter/material.dart';

import '../../models/travel_state.dart';
import '../../services/api_service.dart';
import '../../theme/theme.dart';

/// Fetches `day_specs` once via GET /state, then hands off to
/// [DayPlannerScreen]. Also owns the POST /day-plan submit and its failure
/// handling — without a try/catch here, any non-200 (409 stale session, 400
/// bad payload) escapes as an unhandled async error: [onDone] never runs,
/// nothing is shown, and Continue looks like a dead button.
///
/// A StatefulWidget rather than an inline `FutureBuilder` in the caller: a
/// route's `builder` can re-run on unrelated provider rebuilds, and
/// re-fetching `/state` on every one of those would spend a needless round
/// trip and flash the loading state.
class DayPlannerLoader extends StatefulWidget {
  const DayPlannerLoader({
    super.key,
    required this.api,
    required this.onDone,
    required this.onStale,
    required this.onFailed,
  });

  final ApiService? api;

  /// POST /day-plan succeeded and the thread advanced to `confirm`.
  final VoidCallback onDone;

  /// 409: the thread had already moved past `day_plan` by the time this
  /// screen submitted — the plan on screen is stale. Sending the traveller
  /// back to chat is the honest move, not a generic error.
  final VoidCallback onStale;

  /// Any other failure (400 bad payload, network, timeout) — a bug, not a
  /// stale session, so it's surfaced as an error rather than swallowed.
  final VoidCallback onFailed;

  @override
  State<DayPlannerLoader> createState() => _DayPlannerLoaderState();
}

class _DayPlannerLoaderState extends State<DayPlannerLoader> {
  // Mocks build with no ApiService; day_specs is empty in that case (the
  // Figma-parity mock builds never reach this route since MockChatRepository
  // never sets currentStep to 'day_plan').
  late final Future<List<DaySpec>> _future = widget.api == null
      ? Future.value(const <DaySpec>[])
      : widget.api!.getState().then((s) => s.daySpecs);

  Future<void> _submit(List<DaySpec> days) async {
    try {
      await widget.api?.postDayPlan(days);
      widget.onDone();
    } catch (e) {
      if (_statusCodeOf(e) == 409) {
        widget.onStale();
      } else {
        widget.onFailed();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<DaySpec>>(
      future: _future,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return DayPlannerScreen(initial: snapshot.data!, onSubmit: _submit);
      },
    );
  }
}

/// [ApiService]'s methods all throw a plain `Exception('Backend error
/// $statusCode: $body')` — no typed exception exists in this codebase to
/// carry the code structurally, so this pulls it back out of the message.
/// Null when the failure never reached a response (timeout, network).
final _statusCodePattern = RegExp(r'Backend error (\d+):');
int? _statusCodeOf(Object error) {
  final match = _statusCodePattern.firstMatch(error.toString());
  return match == null ? null : int.tryParse(match.group(1)!);
}

/// Picks an area and a focus for each day of the trip.
///
/// Opens already filled in: the backend writes defaults into `day_specs` the
/// moment intake ends, and this screen displays them. Continuing without
/// changing anything is a valid answer — most travellers will do exactly that.
class DayPlannerScreen extends StatefulWidget {
  const DayPlannerScreen({super.key, required this.initial, required this.onSubmit});

  final List<DaySpec> initial;
  final ValueChanged<List<DaySpec>> onSubmit;

  @override
  State<DayPlannerScreen> createState() => _DayPlannerScreenState();
}

class _DayPlannerScreenState extends State<DayPlannerScreen> {
  late final List<DaySpec> _specs = List.of(widget.initial);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Plan each day')),
      body: ListView.separated(
        padding: const EdgeInsets.all(AppSpacing.lg),
        itemCount: _specs.length,
        separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.md),
        itemBuilder: (context, i) => _DayRow(
          spec: _specs[i],
          onChanged: (s) => setState(() => _specs[i] = s),
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: FilledButton(
            onPressed: () => widget.onSubmit(_specs),
            child: const Text('Continue'),
          ),
        ),
      ),
    );
  }
}

class _DayRow extends StatelessWidget {
  const _DayRow({required this.spec, required this.onChanged});

  final DaySpec spec;
  final ValueChanged<DaySpec> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 56,
          child: Text('Day ${spec.day}', style: AppTextStyles.bodySmall),
        ),
        Expanded(
          child: DropdownButtonFormField<String>(
            // Keyed on the day number, not list position: it's what the test
            // (and any future deep link) addresses a row by, and the two only
            // coincide when specs are already in day order.
            key: ValueKey('region-${spec.day}'),
            initialValue: spec.region,
            isExpanded: true,
            items: [
              for (final e in kRegionLabels.entries)
                DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => v == null ? null : onChanged(spec.copyWith(region: v)),
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          flex: 2,
          child: DropdownButtonFormField<String>(
            key: ValueKey('interest-${spec.day}'),
            initialValue: spec.interest,
            isExpanded: true,
            items: [
              for (final label in kInterestLabels)
                DropdownMenuItem(value: label, child: Text(label)),
            ],
            onChanged: (v) => v == null ? null : onChanged(spec.copyWith(interest: v)),
          ),
        ),
      ],
    );
  }
}
