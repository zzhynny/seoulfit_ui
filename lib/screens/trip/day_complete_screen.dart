import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class DayCompleteScreen extends StatelessWidget {
  const DayCompleteScreen({
    super.key,
    required this.dayNumber,
    required this.onContinue,
    required this.onBack,
  });

  final int dayNumber;
  final VoidCallback onContinue;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();
    final companion = context.watch<CompanionProvider>().selected;
    final day = trip.itinerary!.days.firstWhere((d) => d.dayNumber == dayNumber);
    final total = day.activities.length;
    final visited = day.visitedCount;
    final progress = total == 0 ? 0.0 : visited / total;

    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Row(
            children: [
              GestureDetector(onTap: onBack, child: const Icon(Icons.chevron_left, size: 20)),
              Expanded(
                child: Text('Day $dayNumber Complete', textAlign: TextAlign.center, style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
              ),
              const SizedBox(width: 20),
            ],
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            child: Column(
              children: [
                const SizedBox(height: 32),
                SizedBox(height: 130, child: Image.asset(companion.completeAsset, fit: BoxFit.contain)),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${day.date.toUpperCase()} · ${day.areaName.toUpperCase()}',
                        style: AppTextStyles.bodyMedium.copyWith(color: AppColors.accent, fontWeight: FontWeight.w700, letterSpacing: 0.5),
                      ),
                      const SizedBox(height: 8),
                      Text('$visited of $total places visited', style: AppTextStyles.headingMedium.copyWith(fontSize: 28)),
                      const SizedBox(height: 16),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: progress,
                          minHeight: 8,
                          backgroundColor: AppColors.chipBackground,
                          valueColor: const AlwaysStoppedAnimation(AppColors.primary),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(color: AppColors.chipBackground, borderRadius: BorderRadius.circular(16)),
                        child: Row(
                          children: [
                            Container(
                              width: 16,
                              height: 16,
                              decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                'Nice work! Your stamp book is filling up.',
                                style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: PrimaryButton(label: 'Continue', onPressed: onContinue),
        ),
      ],
    );
  }
}
