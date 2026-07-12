"""
icmr_institute_reference_data.py
==================================
Static reference data about ICMR's 28 constituent institutes that CANNOT be
derived from paper-level bibliometric data - it's compiled by hand from
ICMR's own "Institute Review Meeting" deck (ICMR_Institute_Review_Redesigned.pdf,
20 May 2026, chaired by the Minister of State for Health). Two things live here:

  VISIONS: each institute's stated vision/mission text, used by
  generate_icmr_impact_report.py to build a per-institute "mandate fidelity"
  vocabulary (does published output actually match what the institute says
  its own priorities are).

  POLICY_IMPACT: patents, guidelines, and WHO/national program roles each
  institute self-reported in that same deck - qualitative, self-reported
  information, NOT verified against patent offices or WHO's own records.
  Included so a report can show impact that a citation count would never
  surface (e.g. a WHO Collaborating Centre designation for a small institute
  with few papers).

UPDATING THIS FILE: when a newer Institute Review deck is available, update
the text below by hand - there's no automated way to re-extract it, since
the source is a slide deck, not structured data. Keep the
EXCLUDED_DUPLICATE_VISION list in sync with any new copy-paste errors you
spot in the source deck (two were found in the 20 May 2026 edition - see
below).
"""

# ---------------------------------------------------------------------
# Vision/mission statements, verbatim (condensed to plain sentences,
# stopwords intact - stopword removal happens in generate_icmr_impact_report.py)
# ---------------------------------------------------------------------
VISIONS = {
    "ICMR-National Institute of Virology, Pune":
        "High quality applied and basic research in epidemiology molecular biology immunology diagnostics vaccinology prevention and control strategies for viruses of public health importance",
    "ICMR-National Institute for Research in Tuberculosis, Chennai":
        "generate high quality translational research evidence innovations diagnostics implementation strategies accelerate tuberculosis elimination India",
    "ICMR-National Institute for Research in Bacterial Infections, Kolkata":
        "evidence based research technical support preventive promotive health systems enteric respiratory infections AMR antimicrobial resistance HIV AIDS implementation operational biomedical health research pandemic preparedness",
    "ICMR-National Institute of Malaria Research, Delhi":
        "short term long term solutions malaria vector borne diseases dengue chikungunya diagnosis treatment vector control elimination strategies novel tools",
    "ICMR-National Institute of Translational Virology and AIDS Research, Pune":
        "multidisciplinary research response HIV AIDS translational research capacity medical countermeasures public health",
    "ICMR-National Institute of Vector Control Research, Puducherry":
        "vector borne disease free India prevention control elimination vector borne diseases epidemiological surveillance tools",
    "ICMR-National Institute for Research in Environmental Health, Bhopal":
        "cross disciplinary research innovation environmental health",
    "ICMR-National Institute for Research on Blood and Immune Disorders, Mumbai":
        "globally recognized institute excellence hematology transfusion medicine immunology research diagnostics therapeutics blood immune disorders",
    "ICMR-National Institute of Cancer Prevention and Research, Noida":
        "metabolic processes risk factors tobacco alcohol ultra processed food cancer NCDs non communicable diseases",
    "ICMR-National Institute for Research on Women's Health, Mumbai":
        "improve women reproductive health address child health issues research education healthcare services",
    "ICMR-National Institute of Child Health Research, Delhi":
        "pre eminent institute South Asia child health research national regional policy",
    "ICMR-National Institute of Nutrition, Hyderabad":
        "generate evidence eliminate forms malnutrition India healthy sustainable environment friendly diets lifestyles nutrition",
    "ICMR-National Institute of Traditional Medicine, Belagavi":
        "leading centre excellence evidence based traditional medicine integrative health research validated knowledge affordable innovative scalable solutions",
    "ICMR-National Institute of Epidemiology, Chennai":
        "enhance quality life influence public health practice policies research education training public health school",
    "ICMR-National Institute of NCDs Epidemiology, Bengaluru":
        "leading research centre non communicable disease epidemiology impactful evidence NCD prevention control policy",
    "ICMR-National Institute for Pre-Clinical Research, Hyderabad":
        "state of the art infrastructural facility pre clinical animal experimentation basic applied regulatory research",
    "ICMR-Bhopal Memorial Hospital & Research Centre, Bhopal":
        "ultramodern super specialty medical facilities gas victims research fundamental clinical epidemiology training doctors nurses paramedical",
    "ICMR-National Institute for Research in Digital Health, Delhi":
        "drive impact health innovating enabling facilitating evaluating digital health solutions responsible inclusive equitable health delivery data science",
    "ICMR-National Institute of Health Research, Gorakhpur":
        "operational research Uttar Pradesh Uttarakhand",
    "ICMR-National Institute of Health Research, Dibrugarh":
        "operational research Arunachal Pradesh Assam Manipur Meghalaya Mizoram Nagaland Tripura Sikkim north east",
    "ICMR-National Institute of Health Research, Jodhpur":
        "premier national institute excellence health research transformative innovation strengthen health systems accessible equitable quality healthcare",
    "ICMR-National Institute for Tribal Health Research, Jabalpur":
        "conduct coordinate research health problems health needs tribal country",
    "ICMR-National JALMA Institute for Leprosy & Other Mycobacterial Diseases, Agra":
        "major thrust research programmes leprosy tuberculosis HIV infection leprosy main focus research institute",
    "ICMR-Rajendra Memorial National Institute of Health Research, Patna":
        "globally recognized centre excellence leishmaniasis kala azar vector borne disease research evidence based disease control policies visceral leishmaniasis elimination",
    "ICMR-Regional Medical Research Centre, Sri Vijaya Puram":
        "biomedical research locally prevalent communicable noncommunicable diseases health problems indigenous tribes",
    "ICMR-National Institute of One Health, Nagpur":
        "anchor institution National One Health Mission trans disciplinary human animal environmental health vaccines diagnostics therapeutics zoonotic disease surveillance pandemic preparedness",
}

# Institutes whose vision text in the source deck is a verbatim duplicate of a
# DIFFERENT institute's vision (a copy-paste/templating error in the deck
# itself, confirmed by comparing the text against that institute's actual
# mandate) - excluded from mandate-fidelity scoring rather than scored
# against text that almost certainly isn't really theirs.
EXCLUDED_DUPLICATE_VISION = {
    "ICMR-National Institute of Occupational Health Research, Ahmedabad":
        "source deck's vision text is identical to NIV Pune's (a virus-research description, not occupational health)",
    "ICMR-National Institute of Health Research, Bhubaneswar":
        "source deck's vision text is identical to NIRRCH Mumbai's (a women's/child-health description)",
}

# NOTE ON NAMING: the source deck (20 May 2026 edition) labels the Jabalpur
# institute's slide "ICMR-NIHR, Jabalpur" / "ICMR-National Institute of
# Health Research, Jabalpur" - a DIFFERENT name than icmr_institutes.py's
# current_name for it ("ICMR-National Institute for Tribal Health Research,
# Jabalpur"). Unclear whether this is a newer rename the pipeline's
# institute list hasn't caught up to, or a labeling inconsistency in the
# deck itself - flagged for Pooja to confirm. The VISIONS/POLICY_IMPACT
# dict keys below intentionally use icmr_institutes.py's name (NITHR), since
# that's the name that will actually appear in the "ICMR Institute (Current
# Name)" column of tagged data - keying by the deck's alternate name would
# silently exclude this institute from every reference-data lookup.

# ---------------------------------------------------------------------
# Qualitative policy/program impact - patents, guidelines, WHO/national
# program roles - self-reported per institute in the same review deck.
# Empty string = the deck didn't report one for that institute this cycle,
# NOT "this institute has none".
# ---------------------------------------------------------------------
POLICY_IMPACT = {
    "ICMR-National Institute of Virology, Pune": {
        "patents": "",
        "policy_guidelines": "Validated India's first Mobile BSL-3 laboratory",
        "who_national_role": "Training to WHO SEAR laboratories; national serosurveillance QC (dengue, chikungunya, SARS-CoV-2, measles, rubella)",
    },
    "ICMR-National Institute for Research in Tuberculosis, Chennai": {
        "patents": "3 filed",
        "policy_guidelines": "National Guidance on Differentiated TB Care",
        "who_national_role": "National/Supranational Reference Laboratory for TB (NTEP, WHO-SEARO)",
    },
    "ICMR-National Institute for Research in Bacterial Infections, Kolkata": {
        "patents": "",
        "policy_guidelines": "District-specific antibiotic guidelines (West Bengal, AMR data)",
        "who_national_role": "WHO prequalification (oral cholera vaccine); NTAGI policy rec. (typhoid conjugate vaccine); HIV sentinel surveillance for SACS/NACO",
    },
    "ICMR-National Institute of Malaria Research, Delhi": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "Contributed indigenous multi-stage malaria vaccine candidate (AdFalciVax)",
    },
    "ICMR-National Institute of Translational Virology and AIDS Research, Pune": {
        "patents": "1 filed, 1 applied; 3 copyrights",
        "policy_guidelines": "",
        "who_national_role": "endTB trial evidence in WHO Consolidated Guidelines on TB Treatment & Care",
    },
    "ICMR-National Institute of Vector Control Research, Puducherry": {
        "patents": "",
        "policy_guidelines": "Central Insecticides Board approved ICMR-VCRC's Bti B-17 as Indian Standard",
        "who_national_role": "WHO-recommended molecular xenomonitoring protocol (lymphatic filariasis); designated national reference lab for larvicide testing",
    },
    "ICMR-National Institute of Occupational Health Research, Ahmedabad": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "Training/QC support to WHO SEAR laboratories (shared achievement text with NIV Pune in source deck)",
    },
    "ICMR-National Institute for Research in Environmental Health, Bhopal": {
        "patents": "7 granted",
        "policy_guidelines": "Contributed to India's BTR-1 submission to UNFCCC (Paris Agreement)",
        "who_national_role": "Designated Centre of Excellence by NCDC",
    },
    "ICMR-National Institute for Research on Blood and Immune Disorders, Mumbai": {
        "patents": "",
        "policy_guidelines": "Evidence for national newborn Sickle Cell Disease screening strategy",
        "who_national_role": "",
    },
    "ICMR-National Institute of Cancer Prevention and Research, Noida": {
        "patents": "",
        "policy_guidelines": "Policy inputs against surrogate tobacco advertising; 3 tobacco-tax evidence factsheets",
        "who_national_role": "",
    },
    "ICMR-National Institute for Research on Women's Health, Mumbai": {
        "patents": "",
        "policy_guidelines": "PCOS multidisciplinary model of care adopted",
        "who_national_role": "16 Indian venomous snake codes submitted to WHO (7 accepted)",
    },
    "ICMR-National Institute of Child Health Research, Delhi": {
        "patents": "3 applied",
        "policy_guidelines": "7 guidelines developed",
        "who_national_role": "",
    },
    "ICMR-National Institute of Traditional Medicine, Belagavi": {
        "patents": "1 granted (SARS-CoV-2 phyto-formulation)",
        "policy_guidelines": "",
        "who_national_role": "",
    },
    "ICMR-National Institute for Tribal Health Research, Jabalpur": {
        "patents": "1",
        "policy_guidelines": "",
        "who_national_role": "",
    },
    "ICMR-Bhopal Memorial Hospital & Research Centre, Bhopal": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "AMR data compilation via WHONET",
    },
    "ICMR-National Institute for Research in Digital Health, Delhi": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "HIV estimates used in NACO/MoHFW technical report (2024)",
    },
    "ICMR-National Institute of Health Research, Gorakhpur": {
        "patents": "",
        "policy_guidelines": "Doxycycline/Azithromycin added to state AES management protocols",
        "who_national_role": "COVID-19 genomic surveillance under INSACOG network",
    },
    "ICMR-National Institute of Health Research, Bhubaneswar": {
        "patents": "",
        "policy_guidelines": "IEC materials adopted in National One Health Program (anthrax); ImCovi-Ag COVID test commercialized (2022)",
        "who_national_role": "RCT findings incorporated into National TB Elimination Program",
    },
    "ICMR-National Institute of Health Research, Dibrugarh": {
        "patents": "",
        "policy_guidelines": "Doxycycline+Azithromycin in India's COVID-19 empirical treatment protocol",
        "who_national_role": "",
    },
    "ICMR-National Institute of Health Research, Jodhpur": {
        "patents": "",
        "policy_guidelines": "ICMR Sickle Cell Disease Stigma Scale for India (ISSSI)",
        "who_national_role": "",
    },
    "ICMR-Rajendra Memorial National Institute of Health Research, Patna": {
        "patents": "",
        "policy_guidelines": "First-ever PKDL treatment guideline (via WHO Geneva process)",
        "who_national_role": "WHO reference centre for Leishmania parasite and Sera Bank",
    },
    "ICMR-Regional Medical Research Centre, Sri Vijaya Puram": {
        "patents": "1 granted (MUNISVR device)",
        "policy_guidelines": "Doxycycline recommended for leptospirosis treatment/prophylaxis",
        "who_national_role": "Only WHO Collaborating Centre in SE Asia for Leptospirosis",
    },
    "ICMR-National Institute of One Health, Nagpur": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "Anchor institution for India's National One Health Mission",
    },
    "ICMR-National Institute of Nutrition, Hyderabad": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "",
    },
    "ICMR-National Institute of Epidemiology, Chennai": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "National disease surveillance networks (HIV, rotavirus, invasive bacterial disease, congenital rubella)",
    },
    "ICMR-National Institute of NCDs Epidemiology, Bengaluru": {
        "patents": "",
        "policy_guidelines": "NCRP data supported HPV vaccination policy evidence",
        "who_national_role": "",
    },
    "ICMR-National JALMA Institute for Leprosy & Other Mycobacterial Diseases, Agra": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "",
    },
    "ICMR-National Institute for Pre-Clinical Research, Hyderabad": {
        "patents": "",
        "policy_guidelines": "",
        "who_national_role": "National pandemic-preparedness pre-clinical infrastructure (SPF animal facility)",
    },
}

# ---------------------------------------------------------------------
# The RMRC -> National Institute rename group (see generate_icmr_impact_report.py
# Section 7 - "Regional -> National Mandate Transition"). Update this if ICMR
# renames or establishes further Regional Medical Research Centres.
# ---------------------------------------------------------------------
RMRC_TRANSITION_GROUP = [
    ("ICMR-National Institute of Health Research, Bhubaneswar", "Odisha", "Renamed -> National (NIHR)"),
    ("ICMR-National Institute of Health Research, Dibrugarh", "Assam", "Renamed -> National (NIHR)"),
    ("ICMR-National Institute of Health Research, Gorakhpur", "Uttar Pradesh", "Renamed -> National (NIHR)"),
    ("ICMR-National Institute of Health Research, Jodhpur", "Rajasthan", "Renamed -> National (NIHR)"),
    ("ICMR-Rajendra Memorial National Institute of Health Research, Patna", "Bihar", "Renamed -> National (RM NIHR)"),
    ("ICMR-Regional Medical Research Centre, Sri Vijaya Puram", "Andaman and Nicobar", "STILL Regional (RMRC)"),
]

# ---------------------------------------------------------------------
# Curated disease-focus keyword sets, used ONLY for the international-
# collaboration "partner countries by disease-specific institute" cut in
# Section 6 - a handful of institutes with a narrow, well-known disease
# mandate, not meant to be exhaustive.
# ---------------------------------------------------------------------
DISEASE_FOCUS_KEYWORDS = {
    "TB (NIRT Chennai)": ("ICMR-National Institute for Research in Tuberculosis, Chennai",
                          ["tuberculosis", "tb ", "mycobacterium", "rifampicin", "bedaquiline"]),
    "Malaria (NIMR Delhi)": ("ICMR-National Institute of Malaria Research, Delhi",
                             ["malaria", "plasmodium", "vector", "anopheles", "dengue", "chikungunya"]),
    "HIV/AIDS (NITVAR Pune)": ("ICMR-National Institute of Translational Virology and AIDS Research, Pune",
                               ["hiv", "aids", "antiretroviral", "art regimen"]),
    "Kala-azar (RMNIHR Patna)": ("ICMR-Rajendra Memorial National Institute of Health Research, Patna",
                                 ["leishmania", "kala-azar", "kala azar", "visceral leishmaniasis", "pkdl"]),
    "Vector control (NIVCR Puducherry)": ("ICMR-National Institute of Vector Control Research, Puducherry",
                                          ["vector", "filariasis", "mosquito", "lymphatic filariasis", "aedes", "anopheles"]),
}

# ---------------------------------------------------------------------
# Institute -> ICMR HQ Scientific Division (INFERRED, not an official ICMR
# crosswalk).
#
# ICMR HQ has 12 named Scientific Divisions, each headed by a scientist -
# confirmed real via ICMR's own Contact Directory (icmr.gov.in/contact-
# directory): Communicable Diseases (CD), Non-Communicable Diseases (NCD),
# Reproductive Child Health & Nutrition (RCHN), Discovery Research,
# Development Research, Delivery Research, Descriptive Research, Policy &
# Communication, International Health Division (IHD), Innovation &
# Translation Research (ITR), Bioethics Unit, and DHR Coordination. These
# are HQ-level administrative/thematic divisions that coordinate research
# and extramural funding across ICMR - they are NOT something an author
# would ever cite in their own affiliation string, which is why the old
# "ICMR Division" column (regex-extracted "Division of X"/"Department of
# X" phrasing from affiliation text) was actually surfacing something
# completely different: ad hoc sub-unit/lab names within an institute, not
# ICMR's own org-chart division.
#
# ICMR does NOT publish a public institute -> division crosswalk (checked
# icmr.gov.in/institutes, /organogram, /contact-directory, and
# intent.icmr.org.in - no such table exists). Every value below is
# INFERRED from that institute's stated disease/research focus (using its
# vision text in VISIONS above, or its name/mandate where vision text is
# unavailable/unreliable). Treat this as a defensible best guess, not an
# official ICMR classification - please sanity-check against anything you
# know about each institute's actual reporting line or funding source, and
# correct any entry that's wrong.
#
# Format: institute -> (division_label, rationale)
# ---------------------------------------------------------------------
INSTITUTE_DIVISION = {
    "ICMR-National JALMA Institute for Leprosy & Other Mycobacterial Diseases, Agra":
        ("Communicable Diseases (CD)", "Leprosy, tuberculosis, HIV - core infectious-disease mandate"),
    "ICMR-National Institute of Occupational Health Research, Ahmedabad":
        ("Non-Communicable Diseases (NCD)", "Occupational/environmental exposure -> chronic disease; own vision text unreliable (duplicate of NIV Pune's), classified by institute name/mandate instead"),
    "ICMR-National Institute of Traditional Medicine, Belagavi":
        ("Discovery Research", "Validating traditional-medicine leads = basic/translational drug-discovery research"),
    "ICMR-National Institute of NCDs Epidemiology, Bengaluru":
        ("Non-Communicable Diseases (NCD)", "NCD explicit in institute name and vision text"),
    "ICMR-Bhopal Memorial Hospital & Research Centre, Bhopal":
        ("Non-Communicable Diseases (NCD)", "Long-term chronic-disease research in Bhopal gas-tragedy survivors"),
    "ICMR-National Institute for Research in Environmental Health, Bhopal":
        ("Non-Communicable Diseases (NCD)", "Environmental exposure -> chronic/non-communicable disease research"),
    "ICMR-National Institute of Health Research, Bhubaneswar":
        ("Descriptive Research", "Former RMRC; historic regional multi-disease surveillance mandate (own vision text unreliable - duplicate of NIRRCH Mumbai's)"),
    "ICMR-National Institute for Research in Tuberculosis, Chennai":
        ("Communicable Diseases (CD)", "Tuberculosis"),
    "ICMR-National Institute of Epidemiology, Chennai":
        ("Descriptive Research", "Cross-disease epidemiology, surveillance, public-health training - matches Descriptive Research's definition directly"),
    "ICMR-National Institute of Malaria Research, Delhi":
        ("Communicable Diseases (CD)", "Malaria and other vector-borne disease"),
    "ICMR-National Institute for Research in Digital Health, Delhi":
        ("Innovation & Translation Research (ITR)", "Digital health tools/solutions, data science - technology/diagnostics innovation"),
    "ICMR-National Institute of Child Health Research, Delhi":
        ("Reproductive, Child Health & Nutrition (RCHN)", "Child health"),
    "ICMR-National Institute of Health Research, Dibrugarh":
        ("Delivery Research", "Vision text explicitly says 'operational research' for its NE-India states - matches Delivery Research's health-systems/implementation-research definition"),
    "ICMR-National Institute of Health Research, Gorakhpur":
        ("Delivery Research", "Vision text explicitly says 'operational research' for UP/Uttarakhand - matches Delivery Research's health-systems/implementation-research definition"),
    "ICMR-National Institute of Nutrition, Hyderabad":
        ("Reproductive, Child Health & Nutrition (RCHN)", "Nutrition - explicit in RCHN's own definition"),
    "ICMR-National Institute for Pre-Clinical Research, Hyderabad":
        ("Discovery Research", "Pre-clinical/animal experimentation = basic and translational research infrastructure"),
    "ICMR-National Institute for Tribal Health Research, Jabalpur":
        ("Descriptive Research", "Vision text: characterizing tribal-population health problems/needs - a burden/epidemiology mandate, not a single disease"),
    "ICMR-National Institute of Health Research, Jodhpur":
        ("Non-Communicable Diseases (NCD)", "Formerly NIIRNCD - National Institute for Implementation Research on Non-Communicable Diseases - before its 2026 rename to NIHR; NCD focus confirmed by its own former name"),
    "ICMR-National Institute for Research in Bacterial Infections, Kolkata":
        ("Communicable Diseases (CD)", "Cholera, enteric infections, AMR, HIV surveillance - infectious-disease mandate"),
    "ICMR-National Institute of One Health, Nagpur":
        ("Communicable Diseases (CD)", "Zoonotic disease surveillance and pandemic preparedness; note the One Health mandate is genuinely cross-cutting (human-animal-environment), so this is the least clean-cut assignment in this table"),
    "ICMR-National Institute for Research on Blood and Immune Disorders, Mumbai":
        ("Non-Communicable Diseases (NCD)", "Hematology, transfusion medicine, immune disorders - chronic/non-communicable conditions"),
    "ICMR-National Institute for Research on Women's Health, Mumbai":
        ("Reproductive, Child Health & Nutrition (RCHN)", "Women's reproductive and child health"),
    "ICMR-National Institute of Cancer Prevention and Research, Noida":
        ("Non-Communicable Diseases (NCD)", "Cancer; vision text explicitly says 'NCDs non communicable diseases'"),
    "ICMR-Rajendra Memorial National Institute of Health Research, Patna":
        ("Communicable Diseases (CD)", "Kala-azar/visceral leishmaniasis - vector-borne infectious disease"),
    "ICMR-National Institute of Vector Control Research, Puducherry":
        ("Communicable Diseases (CD)", "Vector-borne disease control"),
    "ICMR-National Institute of Virology, Pune":
        ("Communicable Diseases (CD)", "Viral disease research"),
    "ICMR-National Institute of Translational Virology and AIDS Research, Pune":
        ("Communicable Diseases (CD)", "HIV/AIDS"),
    "ICMR-Regional Medical Research Centre, Sri Vijaya Puram":
        ("Descriptive Research", "Still-regional RMRC; vision text explicitly spans BOTH communicable and non-communicable disease locally - classified by its historic multi-disease surveillance mandate rather than either single disease division"),
}

# Reference list of ICMR's 12 HQ Scientific Divisions, for validation/display.
ICMR_HQ_DIVISIONS = [
    "Communicable Diseases (CD)",
    "Non-Communicable Diseases (NCD)",
    "Reproductive, Child Health & Nutrition (RCHN)",
    "Discovery Research",
    "Development Research",
    "Delivery Research",
    "Descriptive Research",
    "Policy & Communication",
    "International Health Division (IHD)",
    "Innovation & Translation Research (ITR)",
    "Bioethics Unit",
    "DHR Coordination",
]
