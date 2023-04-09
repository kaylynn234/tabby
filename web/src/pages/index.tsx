import Favorite from "@mui/icons-material/Favorite";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Container from '@mui/material/Container';
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

export default function Home() {
  let theme = useTheme();

  return (
    <>
      <Box sx={{ backgroundImage: 'linear-gradient(to bottom, transparent 50%, #EEEEFF)' }}>
        <Container>
          <Grid
            container
            spacing={2}
            sx={{ height: '768px', paddingY: { xs: '48px', sm: '72px', md: '144px' } }}
          >
            <Grid
              item
              xs={12}
              md={6}
            >
              <Stack
                spacing={2}
                sx={{
                  display: 'flex',
                  height: '100%',
                  alignItems: { xs: 'center', md: 'start' },
                  justifyContent: 'center',
                  textAlign: { xs: 'center', md: 'left' }
                }}
              >
                <Typography variant="h3" sx={{ fontWeight: 'bold' }}>
                  A&nbsp;
                  <Box
                    sx={{
                      display: 'inline',
                      textDecorationThickness: '4px',
                      textDecorationStyle: 'solid',
                      textDecorationColor: 'primary.contrastText',
                      textDecorationLine: 'underline',
                      backgroundImage: 'linear-gradient(to right, #4392F1, #1170E4)',
                      color: 'transparent',
                      backgroundClip: 'text'
                    }}
                  >
                    friendlier&nbsp;<wbr />
                  </Box>
                  Discord&nbsp;bot
                </Typography>
                <Typography variant="h6">
                  Tabby stays out of your way so that you can focus on chatting<br />
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                  <Button variant="contained" size="large">Dashboard</Button>
                  <Button variant="outlined" size="large">Add to Discord</Button>
                </Stack>
              </Stack>
            </Grid>
            <Grid item xs={12} md={6} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <img src="/pusheen.png" style={{ maxWidth: '75%', maxHeight: '75%', objectFit: 'scale-down' }} />
            </Grid>
          </Grid>
        </Container>
      </Box>
      <Divider sx={{ marginBottom: 2 }} />
      <Container>
        <Grid container spacing={2} sx={{ paddingY: '48px', textAlign: { xs: 'center', md: 'left' } }}>
          <Grid item xs={12} md={6}>
            <Typography variant='h5' gutterBottom>
              Tabby is open-source
            </Typography>
            <Typography>
              Anybody can contribute to Tabby's development or run their own version of the bot.
              Missing a feature or found a bug?&nbsp;<wbr />
              <Link href="https://github.com/kaylynn234/tabby/issues">Open an issue on GitHub</Link>.
            </Typography>
            <Typography marginTop={1}>
              Made with <Favorite sx={{ fontSize: 'inherit', verticalAlign: 'sub' }} /> by Kaylynn.
            </Typography>
          </Grid>
        </Grid>
      </Container>
    </>
  )
}
