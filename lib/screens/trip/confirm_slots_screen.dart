import 'package:flutter/material.dart';
import '../../models/trip.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class ConfirmSlotsScreen extends StatefulWidget {
  const ConfirmSlotsScreen({
    super.key,
    required this.loadPreferences,
    required this.onGenerate,
    required this.onBack,
  });

  /// Fetches the slots the planner has actually collected, read back from the
  /// thread. Async because it is a round-trip, not screen state.
  final Future<TripPreferences> Function() loadPreferences;

  final VoidCallback onGenerate;
  final VoidCallback onBack;

  @override
  State<ConfirmSlotsScreen> createState() => _ConfirmSlotsScreenState();
}

class _ConfirmSlotsScreenState extends State<ConfirmSlotsScreen> {
  TripPreferences? _preferences;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final preferences = await widget.loadPreferences();
      if (mounted) setState(() => _preferences = preferences);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final preferences = _preferences;
    final onGenerate = widget.onGenerate;
    final onBack = widget.onBack;

    if (preferences == null) {
      return Center(
        child: _failed
            ? Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  "Couldn't read your answers back. Go back to Chat and try "
                  'again.',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.bodyMedium
                      .copyWith(color: AppColors.textSecondary),
                ),
              )
            : const CircularProgressIndicator(),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
          child: IconButton(
            onPressed: onBack,
            icon: const Icon(Icons.chevron_left, size: 28),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Is everything correct?', style: AppTextStyles.headingMedium.copyWith(fontSize: 28)),
              const SizedBox(height: 8),
              Text(
                "Here's what your SeoulFit AI will use to build your customized day-by-day plan.",
                style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: AppColors.border),
                borderRadius: BorderRadius.circular(24),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('My Seoul Itinerary', style: AppTextStyles.headingSmall.copyWith(fontSize: 18)),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppColors.chipBackground,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          'AI READY',
                          style: AppTextStyles.caption.copyWith(
                            color: const Color(0xFF4D6F60),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: _DashedDivider(),
                  ),
                  _SummaryRow(icon: Icons.calendar_today_outlined, label: 'Travel Dates', value: preferences.dateRange),
                  _SummaryRow(icon: Icons.place_outlined, label: 'Region', value: preferences.region),
                  _SummaryRow(icon: Icons.explore_outlined, label: 'Travel Style', value: preferences.travelStyle),
                  _SummaryRow(icon: Icons.people_outline, label: 'Group Size', value: preferences.groupSize),
                  _SummaryRow(icon: Icons.eco_outlined, label: 'Dietary Notes', value: preferences.dietaryNotes),
                  _SummaryRow(icon: Icons.speed_outlined, label: 'Pace', value: preferences.pace, isLast: true),
                ],
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(24),
          child: PrimaryButton(label: 'Generate My Itinerary ✨', onPressed: onGenerate),
        ),
      ],
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.icon,
    required this.label,
    required this.value,
    this.isLast = false,
  });

  final IconData icon;
  final String label;
  final String value;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: isLast
            ? null
            : const Border(bottom: BorderSide(color: AppColors.border)),
      ),
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppColors.chipBackground,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, size: 16, color: AppColors.primary),
              ),
              const SizedBox(width: 12),
              Text(label, style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary)),
            ],
          ),
          Row(
            children: [
              Text(value, style: AppTextStyles.bodyMedium.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(width: 8),
              const Icon(Icons.edit_outlined, size: 14, color: AppColors.textSecondary),
            ],
          ),
        ],
      ),
    );
  }
}

class _DashedDivider extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: const Size(double.infinity, 1),
      painter: _DashPainter(),
    );
  }
}

class _DashPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.border
      ..strokeWidth = 2;
    const dashWidth = 6.0;
    const dashSpace = 4.0;
    double x = 0;
    while (x < size.width) {
      canvas.drawLine(Offset(x, 0), Offset(x + dashWidth, 0), paint);
      x += dashWidth + dashSpace;
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
