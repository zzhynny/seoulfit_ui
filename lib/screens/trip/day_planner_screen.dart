import 'package:flutter/material.dart';

import '../../models/travel_state.dart';
import '../../theme/theme.dart';

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
