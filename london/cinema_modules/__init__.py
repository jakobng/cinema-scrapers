# London Cinema Scraper Modules
# Each module should export a scrape_<cinema_name>() function

from . import bfi_southbank_module
from . import prince_charles_module
from . import garden_cinema_module
from . import nickel_module
from . import barbican_module
from . import genesis_module
from . import ica_module
from . import close_up_module
from . import phoenix_cinema_module
from . import castle_cinema_module
from . import cine_lumiere_module
from . import electric_cinema_module
from . import dochouse_module
from . import rich_mix_module
from . import sands_films_module
from . import rio_cinema_module
from . import lexi_cinema_module
from . import arthouse_crouch_end_module
from . import jw3_module
from . import peckhamplex_module
from . import cinema_museum_module
from . import act_one_module
from . import chiswick_cinema_module
from . import cinema_in_the_arches_module
from . import david_lean_module
from . import regent_street_module
from . import kiln_theatre_module
from . import riverside_studios_module

# Chain scrapers (cover multiple locations)
from . import curzon_chain_module
from . import everyman_chain_module
from . import picturehouse_chain_module

# Additional individual cinemas
from . import bfi_imax_module
from . import cine_real_module
from . import coldharbour_blue_module
from . import olympic_studios_module
from . import the_arzner_module
