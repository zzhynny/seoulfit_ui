import 'package:flutter/material.dart';
import '../../data/repositories/profile_repository.dart';
import '../../models/profile.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class TripRecapScreen extends StatefulWidget {
  const TripRecapScreen({super.key, required this.repository, required this.onDone, required this.onBack});

  final ProfileRepository repository;
  final VoidCallback onDone;
  final VoidCallback onBack;

  @override
  State<TripRecapScreen> createState() => _TripRecapScreenState();
}

class _TripRecapScreenState extends State<TripRecapScreen> {
  bool? _fullRecap;
  List<RecapStop> _stops = [];
  List<RecapStampDay> _stampDays = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final fullRecap = await widget.repository.hasEnoughDataForFullRecap();
    final stops = await widget.repository.fetchRecapStops();
    final stampDays = await widget.repository.fetchStampDays();
    if (!mounted) return;
    setState(() {
      _fullRecap = fullRecap;
      _stops = stops;
      _stampDays = stampDays;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_fullRecap == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Row(
            children: [
              GestureDetector(onTap: widget.onBack, child: const Icon(Icons.chevron_left, size: 20)),
              Expanded(
                child: Text('SeoulFit', textAlign: TextAlign.center, style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
              ),
              const SizedBox(width: 20),
            ],
          ),
        ),
        Expanded(
          child: _fullRecap!
              ? _FullRecapBody(stops: _stops)
              : _LowDataRecapBody(stampDays: _stampDays),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: PrimaryButton(label: 'Done', onPressed: widget.onDone),
        ),
      ],
    );
  }
}

class _FullRecapBody extends StatelessWidget {
  const _FullRecapBody({required this.stops});

  final List<RecapStop> stops;

  static const _positions = [
    Alignment(0.0, -0.85), // 1
    Alignment(-0.7, -0.5), // 2
    Alignment(0.3, -0.05), // 3
    Alignment(-0.5, 0.4), // 4
    Alignment(0.4, 0.7), // 5
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your Trip Recap', style: AppTextStyles.headingMedium.copyWith(fontSize: 26)),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: Container(
              height: 444,
              width: double.infinity,
              decoration: BoxDecoration(
                color: const Color(0xFFFFF8F0),
                border: Border.all(color: AppColors.border),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Stack(
                children: [
                  Positioned.fill(
                    child: Image.asset('assets/images/recap-railway-bg.png', fit: BoxFit.cover),
                  ),
                  Positioned(
                    left: 24,
                    top: 10,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.85),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        'YOUR SEOUL JOURNEY',
                        style: AppTextStyles.caption.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),
                  for (var i = 0; i < stops.length && i < _positions.length; i++)
                    Align(
                      alignment: _positions[i],
                      child: _RecapStopMarker(stop: stops[i]),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _legendDot(AppColors.primary, 'Visited'),
              const SizedBox(width: 16),
              _legendDot(AppColors.border, 'Planned'),
            ],
          ),
          const SizedBox(height: 16),
          Center(
            child: Text(
              'Thanks for exploring Seoul with SeoulFit!',
              textAlign: TextAlign.center,
              style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }

  Widget _legendDot(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 5),
        Text(label, style: AppTextStyles.caption),
      ],
    );
  }
}

class _RecapStopMarker extends StatelessWidget {
  const _RecapStopMarker({required this.stop});

  final RecapStop stop;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Image.asset(
          stop.visited ? 'assets/images/stamp-paw-green.png' : 'assets/images/stamp-paw-empty.png',
          width: 48,
          height: 48,
        ),
        const SizedBox(height: 4),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.85),
            border: Border.all(color: const Color(0xFF5E836A).withValues(alpha: 0.2)),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            children: [
              Text(stop.name, style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
              Text(stop.dayLabel, style: AppTextStyles.caption.copyWith(fontSize: 9, color: const Color(0xFF5E836A))),
            ],
          ),
        ),
      ],
    );
  }
}

class _LowDataRecapBody extends StatelessWidget {
  const _LowDataRecapBody({required this.stampDays});

  final List<RecapStampDay> stampDays;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your Trip Recap', style: AppTextStyles.headingMedium.copyWith(fontSize: 28)),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('YOUR STAMP BOOK', style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600)),
                const SizedBox(height: 14),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    for (final day in stampDays) _stampCell(day),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              "We didn't get enough check-ins to calculate your completion stats this trip - but here's what you collected!",
              style: AppTextStyles.bodySmall.copyWith(height: 1.6),
            ),
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: const Color(0xFFFFF8F0),
              border: Border.all(color: AppColors.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Container(width: 3, height: 70, color: AppColors.primary),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 14, 14, 14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.auto_awesome, size: 14, color: AppColors.textPrimary),
                            const SizedBox(width: 6),
                            Text('Next Time in Seoul', style: AppTextStyles.bodyMedium.copyWith(fontWeight: FontWeight.w700)),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Enable check-ins from the start to unlock your full stamp collection and trip completion stats!',
                          style: AppTextStyles.caption.copyWith(height: 1.5),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _stampCell(RecapStampDay day) {
    final asset = switch (day.state) {
      StampState.visited => 'assets/images/stamp-paw-green.png',
      StampState.partial => 'assets/images/stamp-paw-partial.png',
      StampState.empty => 'assets/images/stamp-paw-empty.png',
    };
    final labelColor = switch (day.state) {
      StampState.visited => AppColors.primary,
      StampState.partial => AppColors.primary,
      StampState.empty => const Color(0xFF9CA3AF),
    };
    return Column(
      children: [
        Image.asset(asset, width: 60, height: 60),
        const SizedBox(height: 6),
        Text('Day ${day.dayNumber}', style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700)),
        Text(day.label, style: AppTextStyles.caption.copyWith(fontSize: 9, color: labelColor)),
      ],
    );
  }
}
