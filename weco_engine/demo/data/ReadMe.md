# WeCo - Data sets

### Authors: Christophe Antoine, Guillaume Caumon and Paul Baville  
© *Copyright ASGA - Association Scientifique pour la Geologie et ses Applications*

All these data sets are used to test or to apply the correlation cost functions (**ccf**) implemented within **WeCo**.

<hr>

## Data set folder structure

Each data set folder consists in at least three WeCo formatted files:
  - **wells.txt** → WeCo file with well data.
  - **option.txt** → WeCo file with correlation options.
  - **outcome.txt** → WeCo file with correlation outcomes.

<hr>

## Toy examples (Synthetic data set)

**Data set 1.1 → to test variance ccf**

This data set consists of three wells, along which synthetical data, which could be assimilated to petrophysical logs, are simulated as functions of the depth

> WeCo well file - **wells.txt**

Along these **three wells**, the data are synthetical logs (**VarData1** and **VarData2**) simulated as functions of the depth (**Depth**).

> WeCo option files - **variance ccf** - *option_i.txt*

List of the options to simulate well correlations using the **variance** correlation cost function (*i* corresponds to a parametrization of the weight ratio, *i.e.*, the importance of one data compared to the other).

→ The correlation input parameters are:
  - *var-data* = VarData1
  - *var-weight* = The value varies from one option file to the other
  - *var-data2* = VarData2
  - *var-weight2* = The value varies from one option file to the other

> WeCo outcome files - **variance ccf** - *outcome_i.txt*

The outcome file stores the *n*-best well correlations simulated using the **variance** correlation cost function (*i* corresponds to the WeCo option file **option_*i*.txt** used to simulate well correlations).

*N.b.*, *n* is given in the option file as a correlation setting.

> You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.1.bat***

<hr>

**Data set 1.2 → to test no-crossing ccf**

This data set consists of three wells, along which synthetical intervals, which cannot be crossed by correlation lines, are simulated as functions of the depth.

> WeCo well file - **wells.txt**

Along these **three wells**, the data are synthetical intervals (**NoCrossing**) simulated as functions of the depth (**Depth**).

> WeCo option file - **no-crossing ccf** - *option.txt*

List of options to simulate well correlations using the **no-crossing** correlation cost function.  

→ The input parameters are:
  - *no-crossing* = NoCrossing

> WeCo outcome file - **no-crossing ccf** - *outcome.txt*

The outcome file stores the *n*-best well correlations simulated using the **no-crossing** correlation cost function.

*N.b.*, *n* is given in the option file as a correlation setting.

> You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.2.bat***

<hr>

**Data set 1.3 → to test distal ccf**

This data set consists of five wells, along which depositional sedimentary facies and relative well distality are simulated as functions of the measured depth.

> WeCo well files - **distal ccf** - *wells_i.txt*

Along these five wells, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**):
  - **wells_A.txt** corresponds to a transverse cross-section in a sedimentary basin margin.
  - **wells_B.txt** corresponds to a longitudinal cross-section in a sedimentary basin margin.
  - **wells_C.txt** corresponds to a transverse cross-section in a sedimentary bay-head delta.

> WeCo option files - **distal ccf** - *option_i.txt*

List of options to simulate well correlations using the **distal** correlation cost function (*i* corresponds to the input WeCo well file *wells_i.txt*).

→ The input parameters are:
  - *dist-distal* = Distality
  - *dist-facies* = Facies
  - *dist-scaling* = 1.0

> WeCo outcome files - **distal ccf** - *outcome_i.txt*

The outcome file stores the *n*-best well correlations simulated using the **distal** cost function (*i* corresponds to the input WeCo well file *wells_i.txt*).

*N.b.*, *n* is given in the option file as a correlation setting.

> You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.3.bat***

<hr>

**Data set 1.4 → to test multi-distal ccf**

This data set consists of five wells, along which depositional sedimentary facies are simulated as function of the measured depth. It is also composed of one text file corresponding to several sediment transport directions to be tested during the correlation.

> External data - **multi-distal ccf** - *multi_distal.txt*

This file is composed of several synthetic sediment transport directions (**Distality**) to be tested during the correlation.

> WeCo well files - **multi-distal ccf** - *wells_i.weco*

Along these five wells, the data are the sedimentary facies interpretation (**Facies**) as function of the measured depth (**Depth**):
  - **wells_A.txt** corresponds to a transverse cross-section in a sedimentary basin margin.
  - **wells_B.txt** corresponds to a longitudinal cross-section in a sedimentary basin margin.
  - **wells_C.txt** corresponds to a transverse cross-section in a sedimentary bay-head delta.

> WeCo option files - **multi-distal ccf** - *option_i.opt*

List of options to simulate well correlations using the **multi-distal** correlation cost function (*i* corresponds to the input WeCo well file *wells_i.weco*).

→ The input parameters are:
  - *multi-dist-distal* = .\data\data_set_1.4\multi_distal.txt
  - *multi-dist-facies* = Facies
  - *multi-dist-scaling* = 1.0

WeCo outcome files - **multi-distal ccf** - *outcome_i.out*

The outcome file stores the *n*-best well correlations simulated using the **multi-distal** cost function (*i* corresponds to the input WeCo well file *wells_i.weco*).

*N.b.*, *n* is given in the option file as a correlation setting.

> You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.4.bat***

<hr>

**Data set 1.5 → to test b3d ccf**

This data set consists of seven wells, along which depositional sedimentary facies and dipmeter data (dip and azimuth) are simulated as functions of the measured depth. It is also composed of two text files corresponding to (1) the conceptual characterization of the depositional profile (the deltaic spatial extension and the sediment transport direction) and (2) the theoretical depositional sedimentary facies distribution and their spatial extension as function of the depositional depth within the conceptual depositional profile.

> *dep_profile.txt*

This file stores the conceptual depositional profiles parameters → the deltaic spatial extension and the sediment transport direction (**dx**, **dy**, **dz**, **sed_dir**).

> *dep_facies.txt*

This file stores the sedimentary facies distribution as a function of the depositional depth → the facies id, its spatial extension and its range of depositional depth (**id**, **dx**, **dy**, **dz**, **z↑**, **z↓**).

> *wells.txt*

Along these **seven wells**, the data are the structural azimuth (**Azimuth**), the structural dip (**Dip**) and the sedimentary facies interpretation (**Facies**) as functions of **Depth** (measured depth).

> *option.txt*

List of options to simulate well correlations using the **3D Bezier** correlation cost function

→ The input parameters are:
  - *azimuth* = Azimuth
  - *depth* = Depth
  - *dip* = Dip
  - *facies-b3d* = Facies
<!--  - *dep-facies-file* = .\data\data_set_1.5\dep_facies.txt -->
<!--  - *dep-profile-file* = .\data\data_set_1.5\dep_profile.txt -->

> *outcome.txt*

The outcome file stores the *n*-best well correlations simulated using the **3D Bezier** cost function.

*N.b.*, *n* is given in the option file as a correlation setting.

> You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.5.bat***

<hr>

## Process-based geomodels (Synthetic data set)

**Data set 2: Dionisos Coastal Deltaic System**
    /!\ to do /!\

<hr>

## Real data sets

**Data set 3: Hugin Formation, Gudrun-Sigrun Field area, Norwegian North Sea**

This data set is composed of **seven wells** provided by **Equinor ASA**, along which well-logs are recorder **sedimentary facies**, **well distality**, and **biostratigraphy** is interpreted:

External data:

* **multi_distal.txt**: This file is composed of several synthetic **sediment transport directions** to be tested, *i.e.*, several **distalities**.

WeCo formatted data:

* **wells_A.txt**: Along these **seven wells**, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**).
* **wells_B.txt**: Along wells **W04** and **W11**, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**).
* **wells_C.txt**: Along wells **W04**, **W05** and **W11**, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**).
* **wells_D.txt**: Along wells **W01**, **W03** and **W07**, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**).
* **wells_E.txt**: Along wells **W07**, **W09** and **W11**, the data are the sedimentary facies interpretation (**Facies**) and the relative well distality interpretation (**Distality**) as functions of the measured depth (**Depth**).

WeCo option files:

* **option_1*i*.txt**: List of options to simulate well correlations using the **distal** correlation cost function (*i* corresponds to the input WeCo well file **wells_*i*.txt**).  
→ The input parameters are:
  - *dist-distal* = Distality
  - *dist-facies* = Facies
  - *dist-scaling* = 1.0

<r>

* **option_2*i*.txt**: List of options to simulate well correlations using the **multi-distal** correlation cost function (*i* corresponds to the input WeCo well file **wells_*i*.txt**).  
→ The input parameters are:
  - *multi-dist-distal* = .\data\data_set_3\multi_distal.txt
  - *multi-dist-facies* = Facies
  - *multi-dist-scaling* = 1.0

WeCo outcome files:

* [**outcome_1*i*.txt**](.\data_set_3): The outcome file stores the *n*-best well correlations simulated using the **distal** cost function (*i* corresponds to the input WeCo well file [**wells_*i*.txt**](.\data_set_3)).  
*N.b.*, *n* is given in the option file as a correlation setting.

* [**outcome_2*i*.txt**](.\data_set_3): The outcome file stores the *n*-best well correlations simulated using the **multi-distal** cost function (*i* corresponds to the input WeCo well file [**wells_*i*.txt**](.\data_set_3)).  
*N.b.*, *n* is given in the option file as a correlation setting.

→ Multiple geological scenarios validation by confronting stratigraphic well correlation simulations to biostratigraphic interpretations (Baville et al., *Annual RING Meeting*, 2022).

<hr>

**Data set 4: Hugin Formation, Sigrun Field area, Norwegian North Sea**

This data set is composed of **two wells** provided by **Equinor ASA**, along which well-logs **sedimentary facies** and **relative well distality** are interpreted (Knaust and Hoth, *Marine and Petroleum Geology*, 2021).

WeCo formatted data:

* **wells.txt**: Along these **two wells**, the data are the relative well distality interpretation (**Distality**), the sedimentary facies interpretation (**Facies**) and additional facies logs whose facies indexes correspond to groups of laterally equivalent facies (**Facies_*i***) as functions of the measured depth (**Depth**).

WeCo option files:

* **option_*i*.txt**: List of options to simulate well correlations using the **distal** correlation cost function (*i* corresponds to the facies log used to compute the correlation **Facies_*i***).  
→ The input parameters are:
  - *dist-distal* = **Distality**
  - *dist-facies* = **Facies_*i***
  - *dist-scaling* = **1.0**

WeCo outcome files:

* **outcome_*i*.txt**: The outcome file stores the *n*-best well correlations simulated using the **distal** cost function (*i* corresponds to the facies log used to compute the correlation **Facies_*i***).  
*N.b.*, *n* is given in the option file as a correlation setting.

→ Stratigraphic subsurface modeling by automatically correlating depositional facies constrained by relative well distality interpretations (Baville et al., *Marine and Petroleum*, 2022).

<hr>

## Geological Demo Datasets

**data_set_quaternary — Quaternary hydrogeology**

100 synthetic wells representing periglacial/glacial Quaternary stratigraphy with
9 facies codes, 6 log curves, and periglacial features (Eiskeil, cryoturbation,
dropstones). See [data_set_quaternary/ReadMe.md](data_set_quaternary/ReadMe.md)
for full description.

**data_set_coal — Coal basin cyclothems**

30 synthetic wells modelling coal-bearing cyclothem sequences with 10 lithologies,
6 log curves, and coal seam correlation. See
[data_set_coal/ReadMe.md](data_set_coal/ReadMe.md) for full description.

**data_set_eage2024 — EAGE 2024 workshop**

Facies-based dataset used for the EAGE 2024 workshop demonstration.

<hr>

<!---
**Data set 5: Neslen Formation, Bryson Canyon, Book Cliffs, USA**

    /!\ to do /!\
-->

<!--
**Data set 1.3 → to test same region ccf**
This data set consists of **three wells**, along which **synthetical intervals** that must be completely correlated are simulated along the **depth**.
WeCo well file:
* **wells.txt**: This data set is composed of three wells, the only data is the **Depth**, and **SameRegion** are synthetical intervals that must be completely correlated.
WeCo option file:
* **option.txt**: List of options to simulate well correlations using the **same-region** correlation cost function.  
→ The input parameters are:
  - *same-region* = SameRegion
WeCo outcome file:
* **outcome.txt**: The outcome file stores the *n*-best well correlations simulated using the **same-region** correlation cost function.  
*N.b.*, *n* is given in the option file as a correlation setting.
→ You can test this data set in the WeCo interface by double-clicking on ***test_data_set_1.3.bat***
<hr>
-->
